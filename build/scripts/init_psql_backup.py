#!/usr/bin/env python3
"""
Backup de PostgreSQL a S3/S3-compatible usando boto3.

- Genera un dump con `pg_dump -Fc -b -v`
- Sube el archivo a s3://<bucket>/backup/<filename>
- Soporta endpoints S3-compatibles (MinIO, etc.) y desactivar verificación SSL
- Configurable por variables de entorno (ver README al final del archivo)

Requisitos: boto3
    pip install boto3
"""

from __future__ import annotations

import logging
import os
import shlex
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

import boto3
from botocore.client import Config as BotoConfig


LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger(__name__)


def _tz_setup() -> None:
    """Ajusta la TZ del proceso si se define TZ (similar a /etc/localtime)."""
    tz = os.getenv("TZ")
    if tz:
        os.environ["TZ"] = tz
        try:
            time.tzset()  # type: ignore[attr-defined]
            logger.debug("Timezone seteada a %s", tz)
        except Exception as exc:
            logger.warning("No se pudo setear TZ con tzset(): %s", exc)


def _require(env_key: str) -> str:
    """Obtiene una variable de entorno o aborta con error legible."""
    val = os.getenv(env_key)
    if not val:
        logger.error("Falta variable de entorno requerida: %s", env_key)
        sys.exit(2)
    return val


def run_pg_dump(tmp_dir: Path, filename: str) -> Path:
    """Ejecuta pg_dump y devuelve la ruta del archivo generado."""
    pg_host = _require("PGHOST")
    pg_port = os.getenv("PGPORT", "5432")
    pg_user = _require("PGUSER")
    pg_db = _require("PGDATABASE")
    pg_password = os.getenv("PGPASSWORD")

    out_path = tmp_dir / filename
    out_path.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        "pg_dump",
        "-h",
        pg_host,
        "-p",
        pg_port,
        "-U",
        pg_user,
        "-Fc",
        "-b",
        "-v",
        "-f",
        str(out_path),
        "-d",
        pg_db,
    ]

    env = os.environ.copy()
    if pg_password:
        env["PGPASSWORD"] = pg_password

    logger.info("Ejecutando: %s", " ".join(shlex.quote(x) for x in cmd))
    try:
        subprocess.run(cmd, env=env, check=True)
    except FileNotFoundError:
        logger.error(
            "No se encontró 'pg_dump' en PATH. Instálalo o agrega su ruta."
        )
        sys.exit(3)
    except subprocess.CalledProcessError as exc:
        logger.error("pg_dump falló con código %s.", exc.returncode)
        sys.exit(exc.returncode or 4)

    if not out_path.exists() or out_path.stat().st_size == 0:
        logger.error("El archivo de backup no se generó o está vacío: %s", out_path)
        sys.exit(5)

    logger.info("Backup creado: %s (%.2f MB)", out_path, out_path.stat().st_size / 1e6)
    return out_path


def build_s3_client() -> boto3.session.Session.client:
    """
    Construye el cliente S3 según CALLREC_DEVICE y vars de entorno:
    - s3-aws: usa config por defecto (sin endpoint_url)
    - s3-minio: endpoint_url=S3_ENDPOINT_MINIO
    - s3-no-check-cert: endpoint_url=S3_ENDPOINT y verify=False
    - default: endpoint_url=S3_ENDPOINT si existe
    """
    callrec_device = os.getenv("CALLREC_DEVICE", "").strip() or "default"
    aws_key = _require("AWS_ACCESS_KEY_ID")
    aws_secret = _require("AWS_SECRET_ACCESS_KEY")
    region = os.getenv("AWS_REGION", "us-east-1")

    endpoint_url: Optional[str] = None
    verify: bool | str = True

    if callrec_device == "s3-aws":
        endpoint_url = None
        verify = True
    elif callrec_device == "s3-minio":
        endpoint_url = _require("S3_ENDPOINT_MINIO")
    elif callrec_device == "s3-no-check-cert":
        endpoint_url = _require("S3_ENDPOINT")
        verify = False
    else:
        endpoint_url = os.getenv("S3_ENDPOINT") or None

    # Addressing style (útil para MinIO): "path" o "virtual"
    addressing_style = os.getenv("S3_ADDRESSING_STYLE", "path").lower()
    if addressing_style not in {"path", "virtual"}:
        addressing_style = "path"

    s3_config = BotoConfig(
        s3={"addressing_style": addressing_style, "signature_version": "s3v4"}
    )

    session = boto3.session.Session(
        aws_access_key_id=aws_key,
        aws_secret_access_key=aws_secret,
        region_name=region,
    )
    client = session.client(
        "s3", endpoint_url=endpoint_url, verify=verify, config=s3_config
    )

    logger.info(
        "Cliente S3 listo (device=%s, endpoint=%s, verify_ssl=%s, addressing=%s)",
        callrec_device,
        endpoint_url or "AWS",
        bool(verify),
        addressing_style,
    )
    return client


def upload_to_s3(
    client,
    local_path: Path,
    bucket: str,
    key_prefix: str = "backup/",
    storage_class: Optional[str] = None,
) -> str:
    """Sube el archivo a S3 y devuelve la key final."""
    key = f"{key_prefix.rstrip('/')}/{local_path.name}"
    extra_args = {}
    if storage_class:
        extra_args["StorageClass"] = storage_class

    logger.info("Subiendo a s3://%s/%s ...", bucket, key)
    try:
        client.upload_file(
            Filename=str(local_path),
            Bucket=bucket,
            Key=key,
            ExtraArgs=extra_args or None,
        )
    except Exception as exc:  # boto3 lanza varias excepciones específicas
        logger.error("Fallo la subida a S3: %s", exc)
        sys.exit(6)

    logger.info("Subida OK: s3://%s/%s", bucket, key)
    return key


def main() -> None:
    _tz_setup()

    backup_filename = _require("BACKUP_FILENAME")
    bucket_name = os.getenv("S3_BUCKET_NAME", "omnileads")
    key_prefix = os.getenv("S3_KEY_PREFIX", "backup/")
    storage_class = os.getenv("S3_STORAGE_CLASS")  # opcional (STANDARD, IA, etc.)
    keep_local = os.getenv("KEEP_LOCAL", "false").lower() == "true"

    tmp_dir = Path(os.getenv("TMPDIR", "/tmp")).resolve()
    local_file = run_pg_dump(tmp_dir=tmp_dir, filename=backup_filename)

    s3_client = build_s3_client()
    upload_to_s3(
        client=s3_client,
        local_path=local_file,
        bucket=bucket_name,
        key_prefix=key_prefix,
        storage_class=storage_class,
    )

    # Emula 'mv' de aws-cli: borra el archivo local tras subirlo, salvo KEEP_LOCAL
    if not keep_local:
        try:
            local_file.unlink(missing_ok=True)  # py>=3.8
            logger.info("Archivo local eliminado: %s", local_file)
        except Exception as exc:
            logger.warning("No se pudo eliminar archivo local: %s", exc)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.error("Interrumpido por el usuario.")
        sys.exit(130)
