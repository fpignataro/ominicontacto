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
#

import json
import logging as _logging
from redis.exceptions import RedisError
from ominicontacto_app.services.redis.connection import create_redis_connection

logger = _logging.getLogger(__name__)

DISPOSITIONS_EVENTS_CHANNEL = 'OML:CHANNEL:DISPOSITIONEVENTS'
DISPOSITIONDATA_CAMP_KEY = 'OML:DISPOSITIONDATA:CAMP:{0}'


class CampaignDispositionsCache:

    @property
    def redis_connection(self):
        if self._redis_connection is None:
            self._redis_connection = create_redis_connection(db=2)

    def record_disposition(self, campaign_id, is_engaged):
        redis_key = DISPOSITIONDATA_CAMP_KEY.format(campaign_id)
        field = 'NOT-ENGAGED'
        if is_engaged:
            field = 'ENGAGED'

        try:
            self.redis_connection.hincrby(redis_key, field, 1)
            self._notify_dispositiondata_event({'type': 'DISPOSITION',
                                                'id': campaign_id,
                                                'engaged': is_engaged})
        except RedisError as e:
            logger.error("Redis record_disposition error: %s", e)

    def _notify_dispositiondata_event(self, event_data):
        try:
            self.redis_connection.publish(DISPOSITIONS_EVENTS_CHANNEL, json.dumps(event_data))
        except RedisError as e:
            logger.error("Redis _notify_dispositiondata_event error: %s", e)

    # TODO: Mecanismos para:
    #  - Regenerar datos del día.
    #  - Limpiar a las 00:00
    #  - Contabilizar RECALIFICACIONES (si corresponde restar o sumar ENGAGED/NOT-ENGAGED)
    #  - Notificar RECALIFICACIONES
