#!/usr/bin/env python3
"""
Restore de PostgreSQL desde S3/S3-compatible usando boto3.

Flujo:
1) Descarga s3://<bucket>/<BACKUP_FILENAME> a TMPDIR (por defecto /tmp), donde
   BACKUP_FILENAME es la clave completa del objeto (por ej. "backup/tenant/file.dump")
2) Ejecuta `pg_restore` contra la base indicada

Requisitos:
    pip install boto3

Variables de entorno (principales):
    BACKUP_FILENAME       (obligatoria)  -> clave completa en S3: "prefijo/archivo"
    S3_BUCKET_NAME        (obligatoria)
    AWS_ACCESS_KEY_ID     (obligatoria)
    AWS_SECRET_ACCESS_KEY (obligatoria)
    CALLREC_DEVICE        (s3-aws | s3-minio | s3-no-check-cert | otro)
    S3_ENDPOINT
    S3_ENDPOINT_MINIO
    TMPDIR                (default: "/tmp")
    TZ                    (opcional)
    KEEP_LOCAL            (true/false, default: true)

[Deprecated]: S3_KEY_PREFIX (ya no se usa)

Conexión a Postgres:
    PGHOST, PGPORT (default 5432), PGUSER, PGDATABASE (obligatoria), PGPASSWORD

Opciones de pg_restore (vía env, todas opcionales):
    RESTORE_VERBOSE=true/false          (default: true)
    RESTORE_CLEAN=true/false            (DROP antes de crear)
    RESTORE_NO_OWNER=true/false
    RESTORE_NO_PRIVILEGES=true/false
    RESTORE_JOBS=4                      (paralelismo, solo con -Fc)
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
    """Configura TZ en el proceso si existe la variable de entorno TZ."""
    tz = os.getenv("TZ")
    if tz:
        os.environ["TZ"] = tz
        try:
            time.tzset()  # type: ignore[attr-defined]
            logger.debug("Timezone seteada a %s", tz)
        except Exception as exc:  # noqa: BLE001
            logger.warning("No se pudo setear TZ con tzset(): %s", exc)


def _require(env_key: str) -> str:
    """Lee una variable de entorno o aborta."""
    val = os.getenv(env_key)
    if not val:
        logger.error("Falta variable de entorno requerida: %s", env_key)
        sys.exit(2)
    return val


def build_s3_client():
    """
    Construye el cliente S3 según CALLREC_DEVICE y variables de entorno.
    - s3-aws: usa AWS por defecto (sin endpoint_url)
    - s3-minio: endpoint_url = S3_ENDPOINT_MINIO
    - s3-no-check-cert: endpoint_url = S3_ENDPOINT, verify = False
    - default: endpoint_url = S3_ENDPOINT (si existe)
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

    addressing_style = os.getenv("S3_ADDRESSING_STYLE", "path").lower()
    if addressing_style not in {"path", "virtual"}:
        addressing_style = "path"

    s3_config = BotoConfig(
        s3={"addressing_style": addressing_style, "signature_version": "s3v4"},
    )

    session = boto3.session.Session(
        aws_access_key_id=aws_key,
        aws_secret_access_key=aws_secret,
        region_name=region,
    )
    client = session.client(
        "s3",
        endpoint_url=endpoint_url,
        verify=verify,
        config=s3_config,
    )

    logger.info(
        "Cliente S3 listo (device=%s, endpoint=%s, verify_ssl=%s, addressing=%s)",
        callrec_device,
        endpoint_url or "AWS",
        bool(verify),
        addressing_style,
    )
    return client


def download_from_s3(
    client,
    bucket: str,
    s3_key: str,
    dest_dir: Path,
) -> Path:
    """
    Descarga el backup desde S3 al directorio destino y devuelve la ruta local.

    Parámetros:
        s3_key: clave completa del objeto en S3 (ej: "backup/tenant/file.dump")
    """
    # Guardamos localmente solo el nombre de archivo, sin subdirectorios.
    local_filename = Path(s3_key).name
    dest_dir.mkdir(parents=True, exist_ok=True)
    local_path = dest_dir / local_filename

    logger.info("Descargando s3://%s/%s -> %s", bucket, s3_key, local_path)
    try:
        client.download_file(Bucket=bucket, Key=s3_key, Filename=str(local_path))
    except Exception as exc:  # noqa: BLE001
        logger.error("Fallo la descarga desde S3: %s", exc)
        sys.exit(6)

    if not local_path.exists() or local_path.stat().st_size == 0:
        logger.error("El archivo descargado no existe o está vacío: %s", local_path)
        sys.exit(7)

    size_mb = local_path.stat().st_size / 1e6
    logger.info("Descarga OK (%0.2f MB): %s", size_mb, local_path)
    return local_path


def run_pg_restore(backup_path: Path) -> None:
    """Ejecuta pg_restore con flags configurables por variables de entorno."""
    pg_db = _require("PGDATABASE")
    pg_host = os.getenv("PGHOST")
    pg_port = os.getenv("PGPORT", "5432")
    pg_user = os.getenv("PGUSER")
    pg_password = os.getenv("PGPASSWORD")

    restore_verbose = os.getenv("RESTORE_VERBOSE", "true").lower() == "true"
    restore_clean = os.getenv("RESTORE_CLEAN", "false").lower() == "true"
    restore_no_owner = os.getenv("RESTORE_NO_OWNER", "false").lower() == "true"
    restore_no_priv = os.getenv("RESTORE_NO_PRIVILEGES", "false").lower() == "true"
    jobs = os.getenv("RESTORE_JOBS")

    cmd = ["pg_restore", "-d", pg_db]

    if pg_host:
        cmd.extend(["-h", pg_host])
    if pg_port:
        cmd.extend(["-p", pg_port])
    if pg_user:
        cmd.extend(["-U", pg_user])

    if restore_verbose:
        cmd.append("-v")
    if restore_clean:
        cmd.append("--clean")
    if restore_no_owner:
        cmd.append("--no-owner")
    if restore_no_priv:
        cmd.append("--no-privileges")
    if jobs:
        cmd.extend(["-j", jobs])

    cmd.append(str(backup_path))

    env = os.environ.copy()
    if pg_password:
        env["PGPASSWORD"] = pg_password

    logger.info("Ejecutando: %s", " ".join(shlex.quote(x) for x in cmd))
    try:
        subprocess.run(cmd, env=env, check=True)
    except FileNotFoundError:
        logger.error("No se encontró 'pg_restore' en PATH.")
        sys.exit(8)
    except subprocess.CalledProcessError as exc:
        logger.error("pg_restore falló con código %s.", exc.returncode)
        sys.exit(exc.returncode or 9)

    logger.info("Restore completado correctamente.")


def main() -> None:
    _tz_setup()

    bucket = _require("S3_BUCKET_NAME")
    # BACKUP_FILENAME ahora es la CLAVE COMPLETA del objeto en S3.
    s3_key = _require("BACKUP_FILENAME")
    tmp_dir = Path(os.getenv("TMPDIR", "/tmp")).resolve()
    keep_local = os.getenv("KEEP_LOCAL", "true").lower() == "true"

    s3_client = build_s3_client()
    local_path = download_from_s3(
        client=s3_client,
        bucket=bucket,
        s3_key=s3_key,
        dest_dir=tmp_dir,
    )

    try:
        run_pg_restore(local_path)
    finally:
        if not keep_local:
            try:
                local_path.unlink(missing_ok=True)
                logger.info("Archivo local eliminado: %s", local_path)
            except Exception as exc:  # noqa: BLE001
                logger.warning("No se pudo eliminar el archivo local: %s", exc)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.error("Interrumpido por el usuario.")
        sys.exit(130)
