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

'use strict'
{
    const $bsm = $('#bs-modal')
    const $bsmDialog = $bsm.find('.modal-dialog')
    const $bsmIframe = $bsm.find('iframe')

    $bsm.on('hidden.bs.modal', function (e) {
        $bsmDialog.removeClass('modal-lg')
        $bsmDialog.removeClass('modal-sm')
        $bsmIframe.attr('src', '')
    })

    $bsm.on('shown.bs.modal', function (e) {
        $bsm.modal('handleUpdate')
    })

    window.addEventListener("message", function (event) {
        if (event.data.id === 'show.bs-modal') {
            const { iframeCss, dialogCls, src } = event.data
            if (iframeCss) {
                $bsmIframe.css(iframeCss)
            }
            if (dialogCls) {
                $bsmDialog.addClass(dialogCls)
            }
            if (src) {
                $bsmIframe.attr('src', src)
            }
            $bsm.modal('show')
        } else if (event.data.id === 'hide.bs-modal') {
            $bsm.modal('hide')
        } else if (event.data.id === 'load.whatsapp-url') {
            $('#wrapperWhatsapp').removeClass('hidden');
            $('#wrapperWebphone').removeClass('active');
            $('#newChat').addClass('invisible');
            $('.whatsapp_panel_view').attr('src', event.data.src);
        }
    })
}
