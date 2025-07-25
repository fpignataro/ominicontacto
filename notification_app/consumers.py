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

import logging
from django.conf import settings
from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from channels.layers import get_channel_layer
from ominicontacto_app.services.dialer.notification.subscription \
    import DialerStatsSubscriptionManager
from supervision_app.services.data_management import SupervisionDataManager
from ominicontacto_app.services.redis.connection import create_redis_connection

logger = logging.getLogger(__name__)


class AgentConsole(AsyncJsonWebsocketConsumer):

    GROUP_USER_CLS = "agent-console"
    GROUP_USER_OBJ = "agent-console-{user_id}"
    GROUPS = [
        GROUP_USER_CLS,
        GROUP_USER_OBJ,
    ]

    async def connect(self):
        self.user = self.scope["user"]

        group_name = AgentConsole.GROUP_USER_OBJ.format(user_id=self.user.id)
        await get_channel_layer().group_send(group_name, {
            "type": "broadcast",
            "payload": {
                "type": "logout",
            }})

        if self.user.is_authenticated and self.user.is_agente:
            for group in self.GROUPS:
                await self.channel_layer.group_add(
                    group.format(user_id=self.user.id), self.channel_name)
            return await self.accept()
        return await self.close()

    async def disconnect(self, close_code):
        for group in self.GROUPS:
            await self.channel_layer.group_discard(
                group.format(user_id=self.user.id), self.channel_name)

    async def broadcast(self, event):
        await self.send_json(event["payload"])


class AgentConsoleWhatsapp(AsyncJsonWebsocketConsumer):

    GROUP_USER_CLS = "agent-console-whatsapp"
    GROUP_USER_OBJ = "agent-console-whatsapp-{user_id}"
    GROUPS = [
        GROUP_USER_CLS,
        GROUP_USER_OBJ,
    ]

    async def connect(self):
        self.user = self.scope["user"]

        if self.user.is_authenticated and self.user.is_agente:
            for group in self.GROUPS:
                await self.channel_layer.group_add(
                    group.format(user_id=self.user.id), self.channel_name)
            return await self.accept()
        return await self.close()

    async def disconnect(self, close_code):
        for group in self.GROUPS:
            await self.channel_layer.group_discard(
                group.format(user_id=self.user.id), self.channel_name)

    async def broadcast(self, event):
        await self.send_json(event["payload"])


class DialerStatsConsumer(AsyncJsonWebsocketConsumer):

    GROUP_USER_CLS = 'supervisor-dialer'
    GROUP_USER_OBJ = 'supervisor-dialer-{user_id}'
    GROUPS = [
        GROUP_USER_CLS,
        GROUP_USER_OBJ,
    ]
    OMNIDIALER_USER_ID = 'omnidialer'

    def __init__(self):
        super(DialerStatsConsumer, self).__init__()
        self.subscription_manager = DialerStatsSubscriptionManager()

    async def connect(self):
        self.is_omnidialer = False
        if 'secret' in self.scope['url_route']['kwargs']:
            # Accept OMNIDIALER Connection
            secret = self.scope['url_route']['kwargs']['secret']
            if secret != settings.OML_OMNIDIALER_SECRET:
                return
            self.is_omnidialer = True
            for group in self.GROUPS:
                await self.channel_layer.group_add(
                    group.format(user_id=self.OMNIDIALER_USER_ID), self.channel_name)
            await self.accept()
            return

        self.user = self.scope['user']
        if self.user.is_authenticated and self.user.get_supervisor_profile():
            for group in self.GROUPS:
                await self.channel_layer.group_add(
                    group.format(user_id=self.user.id), self.channel_name)
            await self.accept()
            self.subscription_manager.add_subscription(self.user)
            return

        return await self.close()

    async def disconnect(self, close_code):
        if not (self.is_omnidialer or hasattr(self, 'user')):
            return
        if self.is_omnidialer:
            user_id = self.OMNIDIALER_USER_ID
        else:
            user_id = self.user.id

        for group in self.GROUPS:
            await self.channel_layer.group_discard(
                group.format(user_id=user_id), self.channel_name)
        if hasattr(self, 'user') and self.user.is_authenticated \
                and self.user.get_supervisor_profile():
            self.subscription_manager.remove_subscription(self.user)

    async def broadcast(self, event):
        await self.send_json(event['payload'])


class SupervisionConsumer(AsyncJsonWebsocketConsumer):

    GROUP_USER_CLS = 'supervision'
    GROUP_USER_OBJ = 'supervision-{user_id}'
    GROUPS = [
        GROUP_USER_CLS,
        GROUP_USER_OBJ,
    ]
    OMNIDIALER_USER_ID = 'omnidialer'

    def __init__(self):
        super(SupervisionConsumer, self).__init__()
        self.redis_oml_connection = create_redis_connection(db=0)
        self.redis_calldata_connection = create_redis_connection(db=2)
        self.data_manager = SupervisionDataManager(self.redis_oml_connection,
                                                   self.redis_calldata_connection)

    async def connect(self):
        try:
            self.section = self.scope['url_route']['kwargs']['section']
            if self.section not in self.data_manager.SECTIONS:
                return await self.close()
            self.user = self.scope['user']
            if self.user.is_authenticated and \
                await database_sync_to_async(self.user.get_supervisor_profile)():
                for group in self.GROUPS:
                    await self.channel_layer.group_add(
                        group.format(user_id=self.user.id), self.channel_name)
                await self.accept()
                initial_data = await database_sync_to_async(self.data_manager.add_subscription)(
                    self.user,
                    self.section,
                )
                return await self.send_json({'initial_data': initial_data})
            return await self.close()
        except Exception as e:
            logger.error(e, exc_info=True)
            return await self.close()

    async def disconnect(self, close_code):
        self.user = self.scope['user']

        for group in self.GROUPS:
            await self.channel_layer.group_discard(
                group.format(user_id=self.user.id), self.channel_name)
        if self.user.is_authenticated and \
            await database_sync_to_async(self.user.get_supervisor_profile)():
            await database_sync_to_async(self.data_manager.remove_subscription)(
                self.user,
                self.section,
            )

    async def broadcast(self, event):
        await self.send_json(event['payload'])
