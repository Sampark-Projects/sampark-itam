<template>
  <Card class="mb-4">
    <template #title>
      <div class="flex align-items-center">
        <i class="pi pi-cog mr-2"></i>
        {{ t('assets.fields.technicalDetails') }}
      </div>
    </template>
    <template #content>
      <div class="grid">
        <div class="col-12 md:col-6">
          <div class="p-field">
            <label for="tag">{{ t('assets.fields.tag') }}</label>
            <InputText id="tag" v-model="form.tag" class="w-full" :placeholder="tagPreview?.next_tag || ''" />
            <small v-if="tagHint" class="tag-hint">{{ tagHint }}</small>
          </div>
        </div>

        <div class="col-12 md:col-6">
          <div class="p-field">
            <label for="serial_number">{{ t('assets.fields.serialNumber') }}</label>
            <InputText id="serial_number" v-model="form.serial_number" class="w-full" />
          </div>
        </div>

        <div class="col-12 md:col-6">
          <div class="p-field">
            <label for="firmware_version">{{ t('assets.fields.firmwareVersion') }}</label>
            <InputText id="firmware_version" v-model="form.firmware_version" class="w-full" />
          </div>
        </div>

        <div class="col-12">
          <div class="p-field">
            <label for="protocols">{{ t('assets.fields.protocols') }}</label>
            <MultiSelect
              id="protocols"
              v-model="form.protocols"
              :options="protocolOptions"
              optionLabel="label"
              optionValue="value"
              :filter="true"
              display="chip"
              :maxSelectedLabels="3"
              class="w-full"
            />
            <div class="mt-2 flex align-items-center">
              <InputText id="new_protocol" v-model="newProtocol" :placeholder="t('assets.actions.addProtocol')" @keyup.enter="addProtocol" class="mr-2" style="width:200px" />
              <Button label="+" @click="addProtocol" size="small" />
            </div>
            <small class="text-gray-600">
              {{ t('assets.strings.protocolsNote') }}
            </small>
          </div>
        </div>
      </div>
    </template>
  </Card>
</template>

<script setup>
import { ref, computed, watch, onMounted, onBeforeUnmount } from 'vue'
import { useI18n } from 'vue-i18n'
import { useToast } from 'primevue/usetoast'
import Card from 'primevue/card'
import InputText from 'primevue/inputtext'
import MultiSelect from 'primevue/multiselect'
import Button from 'primevue/button'
import api from '@/api/api'

const props = defineProps({
  form: { type: Object, required: true }
})

const emit = defineEmits(['update:form'])

const { t } = useI18n()
const toast = useToast()

const newProtocol = ref('')
const protocolOptions = ref([])

// Load supported protocols from backend
const loadSupportedProtocols = async () => {
  try {
    const response = await api.getSupportedProtocols()
    const supportedProtocols = response.data.protocols || []
    
    // Convert to format for MultiSelect
    protocolOptions.value = supportedProtocols.map(protocol => ({
      label: protocol,
      value: protocol
    }))
  } catch (error) {
          console.error('Error loading supported protocols:', error)
    // Fallback to default protocols if API does not work
    protocolOptions.value = [
      { label: 'Modbus', value: 'Modbus' },
      { label: 'Profinet', value: 'Profinet' },
      { label: 'OPC-UA', value: 'OPC-UA' },
      { label: 'EtherNet/IP', value: 'EtherNet/IP' },
      { label: 'BACnet', value: 'BACnet' },
      { label: 'DNP3', value: 'DNP3' },
      { label: 'KNX', value: 'KNX' },
      { label: 'M-Bus', value: 'M-Bus' },
      { label: 'IEC 61850', value: 'IEC 61850' },
      { label: 'S7', value: 'S7' },
      { label: 'MQTT', value: 'MQTT' },
      { label: 'Other', value: 'Other' }
    ]
  }
}

function addProtocol() {
  if (!Array.isArray(props.form.protocols)) {
    props.form.protocols = []
  }
  if (
    newProtocol.value &&
    !props.form.protocols.includes(newProtocol.value)
  ) {
    props.form.protocols.push(newProtocol.value)
    if (!protocolOptions.value.some(opt => opt.value === newProtocol.value)) {
      protocolOptions.value.push({ label: newProtocol.value, value: newProtocol.value })
    }
    newProtocol.value = ''
  }
}

// Naming standard: tell the user what tag a new asset will get when the field is left empty
const tagPreview = ref(null)
let tagTimer = null
let tagSeq = 0

async function loadTagPreview() {
  const seq = ++tagSeq
  const typeId = props.form.asset_type_id
  if (props.form.id || !typeId) {
    tagPreview.value = null
    return
  }
  try {
    const res = await api.getNextAssetTag({ asset_type_id: typeId, site_id: props.form.site_id || undefined })
    if (seq === tagSeq) tagPreview.value = res.data && res.data.next_tag ? res.data : null
  } catch (e) {
    if (seq === tagSeq) tagPreview.value = null
  }
}

const tagHint = computed(() => {
  if (!tagPreview.value) return ''
  return t('assets.tagHint.tagAuto', { tag: tagPreview.value.next_tag }) + ' (' + t('assets.tagHint.tagPattern', { pattern: tagPreview.value.pattern }) + ')'
})

watch(
  () => [props.form.asset_type_id, props.form.site_id, props.form.id],
  () => {
    clearTimeout(tagTimer)
    tagTimer = setTimeout(loadTagPreview, 250)
  },
  { immediate: true }
)

onBeforeUnmount(() => clearTimeout(tagTimer))

onMounted(() => {
  loadSupportedProtocols()
})
</script>

<style scoped>
.tag-hint {
  display: block;
  margin-top: 0.25rem;
  color: var(--sk-text-muted, #6b7a71);
}

.p-field {
  margin-bottom: 1rem;
}

.p-field label {
  display: block;
  margin-bottom: 0.5rem;
  font-weight: 500;
}
</style> 