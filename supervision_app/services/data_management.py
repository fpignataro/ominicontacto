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
        # Recorrer todas las suscripciones y borrar?
        pass

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

    def subscribe(self, campaigns, user):
        raise NotImplementedError()

    def unsubscribe(self, campaign, user):
        raise NotImplementedError()


class AgentsDataManager(AbstractDataManager):
    ID = 'AGENTS'

    def _manager_id(self, user):
        return f'{self.ID}:{user.id}'


class DialerDataManager(AbstractDataManager):
    ID = 'DIALER'

    def _manager_id(self, user):
        return f'{self.ID}:{user.id}'


class InboundDataManager(AbstractDataManager):
    ID = 'IN'

    def _manager_id(self, user):
        return f'{self.ID}:{user.id}'


class OutboundDataManager(AbstractDataManager):
    ID = 'OUT'
    CAMP_TYPES = [Campana.TYPE_DIALER, Campana.TYPE_PREVIEW, Campana.TYPE_MANUAL]
    NOT_ATTENDED_EVENTS = ['NOANSWER', 'CANCEL', 'BUSY', 'CHANUNAVAIL', 'FAIL', 'OTHER',
                           'BLACKLIST', 'CONGESTION', 'NONDIALPLAN', 'ABANDON', 'EXITWITHTIMEOUT',
                           'AMD', 'ABANDONWEL', ]
    CALL_EVENTS = ['DIAL', 'ANSWER', ] + NOT_ATTENDED_EVENTS

    def _manager_id(self, user):
        return f'{self.ID}:{user.id}'

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
            print('Suscribing: ', key, manager_id)

            initial_data[campaign.id] = self._get_initial_data(campaign)

        # TODO Anlizar solo enviar data de campañas con datos
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
        # TODO: Get dispositions
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
        print('Update for: ', event_data)
        if event_data['type'] == 'CAMP':
            if event_data['event'] == 'DIAL':
                return {'campaign_id': event_data['id'], 'field': 'dialed'}
            if event_data['event'] == 'ANSWER':
                return {'campaign_id': event_data['id'], 'field': 'attended'}
            if event_data['event'] in self.NOT_ATTENDED_EVENTS:
                return {'campaign_id': event_data['id'], 'field': 'not_attended'}
        if event_data['type'] == 'DISPOSITION':
            if event_data['engaged']:
                return {'campaign_id': event_data['id'], 'field': 'dispositions'}
