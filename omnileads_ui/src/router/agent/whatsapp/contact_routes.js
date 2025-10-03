import AssignContact from '@/views/agent/whatsapp/contact/assign-contact';
import Index from '@/views/agent/whatsapp/contact/Index';
import { WHATSAPP_URL_NAME } from '@/globals/agent/whatsapp';

export default [
    {
        path: `/${WHATSAPP_URL_NAME}_contact_form.html`,
        name: `${WHATSAPP_URL_NAME}_contact_form`,
        component: Index
    },
    {
        path: '/agent-whatsapp-assign-contact/:conversationId',
        name: 'agent-whatsapp-assign-contact',
        component: AssignContact,
        props: true
    }
];
