<template>
<div>
    <Header :title="`${t('views.whatsapp.contact.campaign')}: ${conversation.campaignName || ''}`" />
    <DataTable class="p-datatable-sm" scrollable scrollHeight="380px" responsiveLayout="scroll" data-key="id" paginator show-gridlines :rows="10" :rowsPerPageOptions="[10, 20, 50, 100]" :value="contacts">
        <Column field="id" :header="t('models.whatsapp.contact.id')" sortable></Column>
        <Column
            v-for="(col, idx) in dbfields"
            :header="col.name"
            :key="idx">
            <template #body="{ data }">
                {{ data.data[col.name] }}
            </template>
        </Column>
        <Column bodyClass="p-1 text-center">
            <template #body="{ data }">
                <Button class="p-button-sm" :label="t('globals.select')" @click="assignContact(data.id)" />
            </template>
        </Column>
        <template v-slot:header>
            <div class="flex align-items-center justify-content-end">
                <span class="p-input-icon-left">
                    <i class="pi pi-search" />
                    <InputText autocomplete="off" icon="pi pi-check"
                        v-model="searchTerm"
                        @input="searchContactsDebounced()"
                        :placeholder="t('globals.find')"
                    />
                </span>
            </div>
        </template>
    </DataTable>

</div>
</template>

<script setup>
import { computed, defineProps, ref, watch } from 'vue';
import { useI18n } from 'vue-i18n';
import { useStore } from 'vuex';
import { useDebounceFn } from '@vueuse/core'
import Header from '@/components/agent/whatsapp/contact/Header';
import { WHATSAPP_LOCALSTORAGE_EVENTS } from '@/globals/agent/whatsapp';

const store = useStore();
const { t } = useI18n();

const props = defineProps({
    conversationId: String
});

const conversation = computed(() => store.state.agtWhatsCoversationInfo);
const contacts = computed(() => store.state.agtWhatsContactSearchResults);
const dbfields = computed(() => store.state.agtWhatsContactDBFields);

const searchTerm = ref();
const searchContactsDebounced = useDebounceFn(searchContacts, 1000);

watch(
    () => props.conversationId,
    async (conversationId) => {
        await store.dispatch('agtWhatsConversationDetail', {
            conversationId,
            $t: t
        });
        searchTerm.value = store.state.agtWhatsCoversationInfo.destination;
        await store.dispatch('agtWhatsContactDBFieldsInit', {
            campaignId: store.state.agtWhatsCoversationInfo.campaignId
        });
        searchContacts();
    },
    { immediate: true }
);

async function assignContact (contactId) {
    await store.dispatch('agtWhatsCoversationAssignContact', {
        conversationId: props.conversationId,
        contactId
    });
    parent.postMessage({ id: 'hide.bs-modal' });
    parent.document.dispatchEvent(new Event(WHATSAPP_LOCALSTORAGE_EVENTS.CONVERSATION.DETAIL_INIT_DATA));
}

async function searchContacts () {
    await store.dispatch('agtWhatsContactSearch', {
        campaignId: store.state.agtWhatsCoversationInfo.campaignId,
        conversationId: props.conversationId,
        filterData: {
            search: searchTerm.value
        }
    });
}
</script>
