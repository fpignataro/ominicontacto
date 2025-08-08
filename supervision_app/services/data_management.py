# -*- coding: utf-8 -*-
# Copyright (C) 2018 Freetech Solutions

# This file is part of OMniLeads

# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Lesser General Public License version 3, as published by
# the Free Software Foundation.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Lesser General Public License for more details.

# You should have received a copy of the GNU Lesser General Public License
# along with this program.  If not, see http://www.gnu.org/licenses/.

from ominicontacto_app.models import Campana
from reportes_app.models import LlamadaLog


def get_event_subscription_key(event_code):
    return f'OML:SUPERVISION:EVENT_SUBSCRIPTIONS:{event_code}'


class SupervisionDataManager:
    AGENTS = 'agents'
    OUTBOUND = 'outbound'
    DIALER = 'dialer'
    INBOUND = 'inbound'
    SECTIONS = [AGENTS, OUTBOUND, DIALER, INBOUND, ]
    """ Calcula la información a actualizar en Supervisión de acuerdo a cada evento ocurrido """

    def __init__(self, redis_oml_connection, redis_calldata_connection):
        self.agents = AgentsDataManager(redis_oml_connection, redis_calldata_connection)
        self.outbound = OutboundDataManager(redis_oml_connection, redis_calldata_connection)
        self.dialer = DialerDataManager(redis_oml_connection, redis_calldata_connection)
        self.inbound = InboundDataManager(redis_oml_connection, redis_calldata_connection)

    def add_subscription(self, user, section):
        campaigns = self._current_campaigns(user)
        if section == self.AGENTS:
            initial_data = self.agents.subscribe(campaigns, user)
        if section == self.OUTBOUND:
            initial_data = self.outbound.subscribe(campaigns, user)
        if section == self.DIALER:
            initial_data = self.dialer.subscribe(campaigns, user)
        if section == self.INBOUND:
            initial_data = self.inbound.subscribe(campaigns, user)
        return initial_data

    def remove_subscription(self, user, section):
        campaigns = self._current_campaigns(user)
        if section == self.AGENTS:
            self.agents.unsubscribe(campaigns, user)
        if section == self.OUTBOUND:
            self.outbound.unsubscribe(campaigns, user)
        if section == self.DIALER:
            self.dialer.unsubscribe(campaigns, user)
        if section == self.INBOUND:
            self.inbound.unsubscribe(campaigns, user)

    def update(self, supervisor_id, section_id, event_data):
        if section_id == AgentsDataManager.ID:
            new_data = self.agents.update(event_data)
        if section_id == OutboundDataManager.ID:
            new_data = self.outbound.update(event_data)
        if section_id == DialerDataManager.ID:
            new_data = self.dialer.update(event_data)
        if section_id == InboundDataManager.ID:
            new_data = self.inbound.update(event_data)
        return new_data

    def _current_campaigns(self, user):
        if user.get_is_administrador():
            return Campana.objects.obtener_actuales()
        else:
            supervisor = user.get_supervisor_profile()
            return supervisor.campanas_asignadas_actuales()


class AbstractDataManager():
    def __init__(self, redis_oml_connection, redis_calldata_connection):
        self.redis_calldata_connection = redis_calldata_connection
        self.redis_oml_connection = redis_oml_connection

    def _manager_id(self, user):
        return f'{self.ID}:{user.id}'

    def subscribe(self, campaigns, user):
        raise NotImplementedError()

    def unsubscribe(self, campaigns, user):
        raise NotImplementedError()


class AgentsDataManager(AbstractDataManager):
    ID = 'AGENTS'


class DialerDataManager(AbstractDataManager):
    ID = 'DIALER'
    CALL_EVENTS = ('DIAL', 'ANSWER', ) + LlamadaLog.EVENTOS_NO_CONEXION \
        + LlamadaLog.EVENTOS_NO_CONTACTACION \
        + LlamadaLog.EVENTOS_NO_DIALOGO

    def subscribe(self, campaigns, user):
        manager_id = self._manager_id(user)
        initial_data = {}

        campaigns = campaigns.filter(type=Campana.TYPE_DIALER)
        for campaign in campaigns:
            # Call Events
            for event in self.CALL_EVENTS:
                event_code = f'CAMP:{campaign.id}:{event}'
                key = get_event_subscription_key(event_code)
                self.redis_calldata_connection.sadd(key, manager_id)
            # Disposiion Events
            event_code = f'DISPOSITION:{campaign.id}'
            key = get_event_subscription_key(event_code)
            self.redis_calldata_connection.sadd(key, manager_id)

            initial_data[campaign.id] = self._get_initial_data(campaign)

        # TODO Analizar solo enviar data de campañas con datos
        return initial_data

    def unsubscribe(self, campaigns, user):
        # Analizar recorrer todas las suscripciones usando un
        # scan('OML:SUPERVISION:EVENT_SUBSCRIPTIONS:*') eliminando el manager_id de todas.
        # Así no quedarian suscripciones fantasmas en caso de que cambien asignaciones de campañas.

        manager_id = self._manager_id(user)
        for campaign in campaigns:
            # CAMP event Types
            for event in self.CALL_EVENTS:
                event_code = f'CAMP:{campaign.id}:{event}'
                key = get_event_subscription_key(event_code)
                self.redis_calldata_connection.srem(key, manager_id)
            # DISPOSITION
            event_code = f'DISPOSITIONS:{campaign.id}'
            key = get_event_subscription_key(event_code)
            self.redis_calldata_connection.srem(key, manager_id)

    def _get_initial_data(self, campaign):
        calldata_key = 'OML:CALLDATA:CAMP:{0}'.format(campaign.id)
        response = self.redis_calldata_connection.hgetall(calldata_key)
        dialed = 0
        attended = 0
        not_attended = 0
        amd = 0
        connections_lost = 0
        dispositions = 0
        status = campaign.estado
        # pending =  0  # TODO: Obtener segun el dialer

        # in_call = 0   # TODO: Se puede calcular llamadas en curso haciendo:
        #               'DIAL' + 'ANSWER' + 'CONNECT' + 'ENTERQUEUE'
        #               - EVENTOS_NO_CONEXION - EVENTOS_FIN_CONEXION
        #    Agregar DISCLAIMER: Posiblemente con transferencias la linea siga "ocupada" pero no
        #                     cuente como conectada...

        # Get CALLDATA sums
        for key, value in response.items():
            _key = key.split(':')  # CALL_TYPE:<call_type>:<event>
            if _key[1] == str(LlamadaLog.LLAMADA_DIALER):  # call_type
                event = _key[-1]
                if event == 'DIAL':
                    dialed = value
                elif event == 'CONNECT':
                    attended = value
                elif event in LlamadaLog.EVENTOS_NO_CONTACTACION:
                    not_attended += int(value)
                elif event in LlamadaLog.EVENTOS_NO_DIALOGO:
                    connections_lost += int(value)
                    if event == 'AMD':
                        amd = value
        # Get dispositions
        dispositiondata_key = 'OML:DISPOSITIONDATA:CAMP:{0}'.format(campaign.id)
        response = self.redis_calldata_connection.hget(dispositiondata_key, 'ENGAGED')
        if response:
            dispositions = response

        return {
            'dialed': dialed,
            'attended': attended,
            'not_attended': not_attended,
            'amd': amd,
            'connections_lost': connections_lost,
            'dispositions': dispositions,
            'status': status,
        }

    def update(self, event_data):
        if event_data['type'] == 'CAMP':
            if event_data['call_type'] != str(LlamadaLog.LLAMADA_DIALER):
                return
            if event_data['event'] == 'DIAL':
                return {'campaign_id': event_data['id'], 'field': 'dialed'}
            if event_data['event'] == 'CONNECT':
                return {'campaign_id': event_data['id'], 'field': 'attended'}
            if event_data['event'] in LlamadaLog.EVENTOS_NO_CONTACTACION:
                return {'campaign_id': event_data['id'], 'field': 'not_attended'}
            if event_data['event'] == 'AMD':
                return {'campaign_id': event_data['id'], 'field': 'amd'}
                # En este caso, incrementar también connections_lost
            if event_data['event'] in LlamadaLog.EVENTOS_NO_DIALOGO:
                return {'campaign_id': event_data['id'], 'field': 'connections_lost'}
        if event_data['type'] == 'DISPOSITION':
            delta = 0
            if event_data['engaged']:
                delta = 1
            elif not event_data['engaged'] and event_data['has_previous_different']:
                delta = -1
            if delta:
                return {
                    'campaign_id': event_data['id'],
                    'field': 'dispositions',
                    'delta': delta
                }

    # ================================================
    # TODO: ESTE CODIGO QUEDA COMO REFERENCIA DE COMO SE CALCULABA ANTES - Borrarlo
    # def _contabilizar_llamadas_pendientes(self):
    #     dialer_service = get_dialer_service()
    #     pendientes_por_id = dialer_service.obtener_llamadas_pendientes_por_id(self.campanas)
    #     for campana_id, pendientes in pendientes_por_id.items():
    #         if campana_id not in self.estadisticas:
    #             self._inicializar_conteo_de_campana(campana_id)
    #         self.estadisticas[campana_id]['pendientes'] = pendientes

    # def _contabilizar_llamadas_en_curso(self):
    #     campanas_ids = []
    #     for campana_id, campana in self.campanas.items():
    #         if campana.estado == Campana.ESTADO_ACTIVA:
    #             campanas_ids.append(str(campana_id))
    #     if not campanas_ids:
    #         return
    #     campanas_ids = ','.join(campanas_ids)

    #     # Busco llamadas cuyo ultimo evento sea de llamada en curso
    #     sql = """
    #         SELECT l1.campana_id, COUNT(*) from reportes_app_llamadalog l1
    #         WHERE l1.event IN ('DIAL', 'ANSWER', 'CONNECT', 'ENTERQUEUE') AND l1.id IN (
    #             SELECT MAX(l2.id) FROM reportes_app_llamadalog l2
    #             WHERE l2.campana_id in ({0}) AND l2.tipo_llamada = '{1}' AND
    #             l2.time BETWEEN %(fecha_desde)s AND %(fecha_hasta)s
    #             GROUP BY l2.callid
    #           )
    #         GROUP BY l1.campana_id;
    #     """.format(campanas_ids, str(Campana.TYPE_DIALER))
    #     params = {'fecha_desde': self.desde, 'fecha_hasta': self.hasta}
    #     cursor = connection.cursor()
    #     cursor.execute(sql, params)
    #     values = cursor.fetchall()
    #     for campana_id, cantidad in values:
    #         self.estadisticas[campana_id]['canales_discando'] = cantidad
    # ================================================


class InboundDataManager(AbstractDataManager):
    ID = 'IN'

    def subscribe(self, campaigns, user):
        manager_id = self._manager_id(user)
        initial_data = {}
        campaigns_ids = []

        campaigns = campaigns.filter(type=Campana.TYPE_ENTRANTE)
        for campaign in campaigns:
            # Call Events
            event_code = f'CAMP:{campaign.id}:EXITWITHTIMEOUT'
            key = get_event_subscription_key(event_code)
            self.redis_calldata_connection.sadd(key, manager_id)
            # Wait time
            event_code = f'WAIT:{campaign.id}'
            key = get_event_subscription_key(event_code)
            self.redis_calldata_connection.sadd(key, manager_id)
            # Disposiion Events
            event_code = f'DISPOSITION:{campaign.id}'
            key = get_event_subscription_key(event_code)
            self.redis_calldata_connection.sadd(key, manager_id)
            # Abandon Wait Events
            event_code = f'ABANDON:{campaign.id}'
            key = get_event_subscription_key(event_code)
            self.redis_calldata_connection.sadd(key, manager_id)
            # Queue Size Events
            event_code = f'QUEUE:{campaign.id}'
            key = get_event_subscription_key(event_code)
            self.redis_calldata_connection.sadd(key, manager_id)

            campaigns_ids.append(campaign.id)
            initial_data[campaign.id] = self._get_initial_data(campaign)
        self._set_initial_queue_sizes(campaigns_ids, initial_data)

        # TODO Analizar solo enviar data de campañas con datos
        return initial_data

    def unsubscribe(self, campaigns, user):
        # Analizar recorrer todas las suscripciones usando un
        # scan('OML:SUPERVISION:EVENT_SUBSCRIPTIONS:*') eliminando el manager_id de todas.
        # Así no quedarian suscripciones fantasmas en caso de que cambien asignaciones de campañas.
        manager_id = self._manager_id(user)
        campaigns = campaigns.filter(type=Campana.TYPE_ENTRANTE)
        for campaign in campaigns:
            # Call Events
            event_code = f'CAMP:{campaign.id}:EXITWITHTIMEOUT'
            key = get_event_subscription_key(event_code)
            self.redis_calldata_connection.srem(key, manager_id)
            # Wait time
            event_code = f'WAIT:{campaign.id}'
            key = get_event_subscription_key(event_code)
            self.redis_calldata_connection.srem(key, manager_id)
            # Disposiion Events
            event_code = f'DISPOSITION:{campaign.id}'
            key = get_event_subscription_key(event_code)
            self.redis_calldata_connection.srem(key, manager_id)
            # Abandon Wait Events
            event_code = f'ABANDON:{campaign.id}'
            key = get_event_subscription_key(event_code)
            self.redis_calldata_connection.srem(key, manager_id)
            # Queue Size Events
            event_code = f'QUEUE:{campaign.id}'
            key = get_event_subscription_key(event_code)
            self.redis_calldata_connection.srem(key, manager_id)

    def _get_initial_data(self, campaign):
        attended = 0
        wait_time_sum = 0
        expired = 0
        dispositions = 0
        abandons = 0
        abandons_sum = 0

        # Get expired from CALLDATA:CAMP
        calldata_key = 'OML:CALLDATA:CAMP:{0}'.format(campaign.id)
        field = f'CALL_TYPE:{Campana.TYPE_ENTRANTE}:EXITWITHTIMEOUT'
        response = self.redis_calldata_connection.hget(calldata_key, field)
        if response:
            expired = response
        # Get attended + wait times sum:
        wait_time_key = 'OML:CALLDATA:WAIT-TIME:CAMP:{0}'.format(campaign.id)
        wait_times = self.redis_calldata_connection.lrange(wait_time_key, 0, -1)
        for time in wait_times:
            attended += 1
            wait_time_sum += int(time)
        # Get dispositions
        dispositiondata_key = 'OML:DISPOSITIONDATA:CAMP:{0}'.format(campaign.id)
        response = self.redis_calldata_connection.hget(dispositiondata_key, 'ENGAGED')
        if response:
            dispositions = response
        # Get abandons
        abandon_time_key = 'OML:CALLDATA:ABANDON-TIME:CAMP:{0}'.format(campaign.id)
        abandon_times = self.redis_calldata_connection.lrange(abandon_time_key, 0, -1)
        for time in abandon_times:
            abandons += 1
            abandons_sum += int(time)

        return {
            'attended': attended,
            'total_wait_time': wait_time_sum,
            'expired': expired,
            'abandons': abandons,
            'total_abandon_time': abandons_sum,
            'dispositions': dispositions,
            'queue_size': 0,
        }

    def update(self, event_data):
        if event_data['type'] == 'CAMP':
            if event_data['event'] == 'EXITWITHTIMEOUT':
                return {'campaign_id': event_data['id'], 'field': 'expired'}
        if event_data['type'] == 'WAIT':
            return {'campaign_id': event_data['id'], 'field': 'attended',
                    'wait_time': event_data['time']}
        if event_data['type'] == 'ABANDON':
            return {'campaign_id': event_data['id'], 'field': 'abandons',
                    'time': event_data['time']}
        if event_data['type'] == 'DISPOSITION':
            delta = 0
            if event_data['engaged']:
                delta = 1
            elif not event_data['engaged'] and event_data['has_previous_different']:
                delta = -1
            if delta:
                return {
                    'campaign_id': event_data['id'],
                    'field': 'dispositions',
                    'delta': delta
                }
            return
        if event_data['type'] == 'QUEUE':
            return {'campaign_id': event_data['id'], 'field': 'queue_size',
                    'size': event_data['size']}

    def _set_initial_queue_sizes(self, campaigns_ids, initial_data):
        CALLDATA_QUEUE_SIZE_KEY = 'OML:CALLDATA:QUEUE-SIZE:{0}'
        keys = [CALLDATA_QUEUE_SIZE_KEY.format(campaign_id) for campaign_id in campaigns_ids]
        sizes = self.redis_calldata_connection.mget(keys)
        i = 0
        for campaign_id in campaigns_ids:
            size = sizes[i]
            if size is not None:
                initial_data[campaign_id]['queue_size'] = int(size)
            i += 1


class OutboundDataManager(AbstractDataManager):
    ID = 'OUT'
    CAMP_TYPES = [Campana.TYPE_DIALER, Campana.TYPE_PREVIEW, Campana.TYPE_MANUAL]
    NOT_ATTENDED_EVENTS = LlamadaLog.EVENTOS_NO_CONEXION
    CALL_EVENTS = ('DIAL', 'ANSWER', ) + NOT_ATTENDED_EVENTS

    def subscribe(self, campaigns, user):
        manager_id = self._manager_id(user)
        initial_data = {}

        campaigns = campaigns.filter(type__in=self.CAMP_TYPES)
        for campaign in campaigns:
            # Call Events
            for event in self.CALL_EVENTS:
                event_code = f'CAMP:{campaign.id}:{event}'
                key = get_event_subscription_key(event_code)
                self.redis_calldata_connection.sadd(key, manager_id)
            # Disposiion Events
            event_code = f'DISPOSITION:{campaign.id}'
            key = get_event_subscription_key(event_code)
            self.redis_calldata_connection.sadd(key, manager_id)

            initial_data[campaign.id] = self._get_initial_data(campaign)

        # TODO Analizar solo enviar data de campañas con datos
        return initial_data

    def unsubscribe(self, campaign, user):
        # Analizar recorrer todas las suscripciones usando un
        # scan('OML:SUPERVISION:EVENT_SUBSCRIPTIONS:*') eliminando el manager_id de todas.
        # Así no quedarian suscripciones fantasmas en caso de que cambien asignaciones de campañas.

        manager_id = self._manager_id(user)
        # CAMP event Types
        for event in self.CALL_EVENTS:
            event_code = f'CAMP:{campaign.id}:{event}'
            key = get_event_subscription_key(event_code)
            self.redis_calldata_connection.srem(key, manager_id)
        # DISPOSITION
        event_code = f'DISPOSITIONS:{campaign.id}'
        key = get_event_subscription_key(event_code)
        self.redis_calldata_connection.srem(key, manager_id)

    def _get_initial_data(self, campaign):
        calldata_key = 'OML:CALLDATA:CAMP:{0}'.format(campaign.id)
        response = self.redis_calldata_connection.hgetall(calldata_key)
        dialed = 0
        attended = 0
        not_attended = 0
        dispositions = 0
        # Get CALLDATA sums
        for key, value in response.items():
            event = key.split(':')[-1]
            if event == 'DIAL':
                dialed = value
            if event == 'ANSWER':
                attended = value
            if event in self.NOT_ATTENDED_EVENTS:
                not_attended += int(value)
        # Get dispositions
        dispositiondata_key = 'OML:DISPOSITIONDATA:CAMP:{0}'.format(campaign.id)
        response = self.redis_calldata_connection.hget(dispositiondata_key, 'ENGAGED')
        if response:
            dispositions = response

        return {
            'dialed': dialed,
            'attended': attended,
            'not_attended': not_attended,
            'dispositions': dispositions,
        }

    def update(self, event_data):
        if event_data['type'] == 'CAMP':
            if event_data['event'] == 'DIAL':
                return {'campaign_id': event_data['id'], 'field': 'dialed'}
            if event_data['event'] == 'ANSWER':
                return {'campaign_id': event_data['id'], 'field': 'attended'}
            if event_data['event'] in self.NOT_ATTENDED_EVENTS:
                return {'campaign_id': event_data['id'], 'field': 'not_attended'}
        if event_data['type'] == 'DISPOSITION':
            delta = 0
            if event_data['engaged']:
                delta = 1
            elif not event_data['engaged'] and event_data['has_previous_different']:
                delta = -1
            if delta:
                return {
                    'campaign_id': event_data['id'],
                    'field': 'dispositions',
                    'delta': delta
                }
