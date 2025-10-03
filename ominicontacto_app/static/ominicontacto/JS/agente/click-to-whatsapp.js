/* Copyright (C) 2025 Freetech Solutions

 This file is part of OMniLeads

 This program is free software: you can redistribute it and/or modify
 it under the terms of the GNU Lesser General Public License version 3, as published by
 the Free Software Foundation.

 This program is distributed in the hope that it will be useful,
 but WITHOUT ANY WARRANTY; without even the implied warranty of
 MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 GNU Lesser General Public License for more details.

 You should have received a copy of the GNU Lesser General Public License
 along with this program.  If not, see http://www.gnu.org/licenses/.

*/

/* global Swal, Urls */

'use strict';
{
    const urls = {
        'conversation-new': '/static/omnileads-frontend/agent-whatsapp-conversation-new',
        'conversation-detail': '/static/omnileads-frontend/agent_whatsapp_conversation',
    };
    
    $(document).on('click', '[data-action="click-to-whatsapp"]', function (event) {
        const { 
            campaignId: campaign,
            contactId: contact,
            whatsapp
        } = this.dataset;
        jQuery.ajax({
            url: Urls['v1:conversacion-open'](),
            type: 'get',
            data: { campaign, contact, whatsapp }
        }).then(
            function (data, textStatus, jqXHR) {
                const message = {
                    id: 'load.whatsapp-url',
                    src: `${urls['conversation-detail']}/${data.conversation}`,
                };
                if (data.conversation_granted) {
                    parent.postMessage(message);
                } else {
                    jQuery.ajax({
                        url: Urls['v1:conversacion-attend-chat'](data.conversation),
                        type: 'post',
                    }).then(
                        function (data, textStatus, jqXHR) {
                            parent.postMessage(message);
                        },
                        function (jqXHR, textStatus, errorThrown) {}
                    );
                }
                
            },
            function (jqXHR, textStatus, errorThrown) {
                if (jqXHR.status === 404) {
                    parent.postMessage({
                        id: 'show.bs-modal',
                        dialogCls: 'modal-lg',
                        iframeCss: { height: '550px' },
                        src: `${urls['conversation-new']}?campaign=${campaign}&contact=${contact}&whatsapp=${whatsapp}`
                    });
                } else {
                    Swal.fire({ text: Object.values(jqXHR.responseJSON).join(' '), icon: 'error' });
                }
            },
        );
    });
}
