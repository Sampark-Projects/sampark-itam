<!--
  - AssetLifecycleForm.vue
  - OT lifecycle data: classification and ownership, procurement, commissioning and
  - acceptance, warranty / AMC / support / licence. Every field is optional.
  - Date fields hold Date objects here; AssetForm converts them to and from "YYYY-MM-DD".
-->
<template>
  <Card class="mb-4">
    <template #title>
      <div class="flex align-items-center">
        <i class="pi pi-sync mr-2"></i>
        {{ t('assets.lifecycle.title') }}
      </div>
    </template>
    <template #content>
      <!-- Classification and ownership -->
      <h4 class="lifecycle-group">{{ t('assets.lifecycle.classification') }}</h4>
      <div class="grid">
        <div class="col-12 md:col-4">
          <div class="p-field">
            <label for="safety_relevance">{{ t('assets.lifecycle.fields.safetyRelevance') }}</label>
            <Dropdown
              id="safety_relevance"
              v-model="form.safety_relevance"
              :options="safetyOptions"
              optionLabel="label"
              optionValue="value"
              showClear
              class="w-full"
            />
          </div>
        </div>
        <div class="col-12 md:col-4">
          <div class="p-field">
            <label for="parent_asset_id">{{ t('assets.lifecycle.fields.componentOf') }}</label>
            <AssetParentPicker v-model="form.parent_asset_id" :initial="form.parent" :exclude-id="form.id" />
          </div>
        </div>
        <div class="col-12 md:col-4">
          <div class="p-field">
            <label for="plant_owner">{{ t('assets.lifecycle.fields.plantOwner') }}</label>
            <InputText id="plant_owner" v-model="form.plant_owner" maxlength="255" class="w-full" />
          </div>
        </div>
        <div class="col-12 md:col-4">
          <div class="p-field">
            <label for="amc_partner">{{ t('assets.lifecycle.fields.amcPartner') }}</label>
            <InputText id="amc_partner" v-model="form.amc_partner" maxlength="255" class="w-full" />
          </div>
        </div>
      </div>

      <!-- Procurement -->
      <h4 class="lifecycle-group">{{ t('assets.lifecycle.procurement') }}</h4>
      <div class="grid">
        <div class="col-12 md:col-4">
          <div class="p-field">
            <label for="requisition_number">{{ t('assets.lifecycle.fields.requisitionNumber') }}</label>
            <InputText id="requisition_number" v-model="form.requisition_number" maxlength="100" class="w-full" />
          </div>
        </div>
        <div class="col-12 md:col-4">
          <div class="p-field">
            <label for="purchase_order_number">{{ t('assets.lifecycle.fields.purchaseOrderNumber') }}</label>
            <InputText id="purchase_order_number" v-model="form.purchase_order_number" maxlength="100" class="w-full" />
          </div>
        </div>
        <div class="col-12 md:col-4">
          <div class="p-field">
            <label for="purchase_date">{{ t('assets.lifecycle.fields.purchaseDate') }}</label>
            <Calendar id="purchase_date" v-model="form.purchase_date" dateFormat="dd/mm/yy" showIcon class="w-full" />
          </div>
        </div>
        <div class="col-12 md:col-4">
          <div class="p-field">
            <label for="expected_delivery_date">{{ t('assets.lifecycle.fields.expectedDeliveryDate') }}</label>
            <Calendar id="expected_delivery_date" v-model="form.expected_delivery_date" dateFormat="dd/mm/yy" showIcon class="w-full" />
          </div>
        </div>
        <div class="col-12 md:col-4">
          <div class="p-field">
            <label for="received_date">{{ t('assets.lifecycle.fields.receivedDate') }}</label>
            <Calendar id="received_date" v-model="form.received_date" dateFormat="dd/mm/yy" showIcon class="w-full" />
          </div>
        </div>
        <div class="col-12 md:col-4">
          <div class="p-field">
            <label for="purchase_cost">{{ t('assets.lifecycle.fields.purchaseCost') }}</label>
            <InputNumber id="purchase_cost" v-model="form.purchase_cost" :min="0" :minFractionDigits="0" :maxFractionDigits="2" class="w-full" />
          </div>
        </div>
        <div class="col-12 md:col-4">
          <div class="p-field">
            <label for="cost_currency">{{ t('assets.lifecycle.fields.costCurrency') }}</label>
            <InputText id="cost_currency" v-model="form.cost_currency" maxlength="3" class="w-full currency-input" />
          </div>
        </div>
      </div>

      <!-- Commissioning and acceptance -->
      <h4 class="lifecycle-group">{{ t('assets.lifecycle.commissioning') }}</h4>
      <div class="grid">
        <div class="col-12 md:col-4">
          <div class="p-field">
            <label for="commissioned_date">{{ t('assets.lifecycle.fields.commissionedDate') }}</label>
            <Calendar id="commissioned_date" v-model="form.commissioned_date" dateFormat="dd/mm/yy" showIcon class="w-full" />
          </div>
        </div>
        <div class="col-12 md:col-4">
          <div class="p-field">
            <label for="acceptance_date">{{ t('assets.lifecycle.fields.acceptanceDate') }}</label>
            <Calendar id="acceptance_date" v-model="form.acceptance_date" dateFormat="dd/mm/yy" showIcon class="w-full" />
          </div>
        </div>
        <div class="col-12 md:col-4">
          <div class="p-field">
            <label for="acceptance_signed_by">{{ t('assets.lifecycle.fields.acceptanceSignedBy') }}</label>
            <InputText id="acceptance_signed_by" v-model="form.acceptance_signed_by" maxlength="255" class="w-full" />
          </div>
        </div>
      </div>

      <!-- Warranty and support -->
      <h4 class="lifecycle-group">{{ t('assets.lifecycle.support') }}</h4>
      <div class="grid">
        <div class="col-12 md:col-3">
          <div class="p-field">
            <label for="warranty_expiry_date">{{ t('assets.lifecycle.fields.warrantyExpiryDate') }}</label>
            <Calendar id="warranty_expiry_date" v-model="form.warranty_expiry_date" dateFormat="dd/mm/yy" showIcon class="w-full" />
          </div>
        </div>
        <div class="col-12 md:col-3">
          <div class="p-field">
            <label for="amc_expiry_date">{{ t('assets.lifecycle.fields.amcExpiryDate') }}</label>
            <Calendar id="amc_expiry_date" v-model="form.amc_expiry_date" dateFormat="dd/mm/yy" showIcon class="w-full" />
          </div>
        </div>
        <div class="col-12 md:col-3">
          <div class="p-field">
            <label for="support_expiry_date">{{ t('assets.lifecycle.fields.supportExpiryDate') }}</label>
            <Calendar id="support_expiry_date" v-model="form.support_expiry_date" dateFormat="dd/mm/yy" showIcon class="w-full" />
          </div>
        </div>
        <div class="col-12 md:col-3">
          <div class="p-field">
            <label for="licence_expiry_date">{{ t('assets.lifecycle.fields.licenceExpiryDate') }}</label>
            <Calendar id="licence_expiry_date" v-model="form.licence_expiry_date" dateFormat="dd/mm/yy" showIcon class="w-full" />
          </div>
        </div>
      </div>

      <!-- Disposal or return (filled in during retirement) -->
      <h4 class="lifecycle-group">{{ t('assets.lifecycle.disposal') }}</h4>
      <div class="grid">
        <div class="col-12 md:col-4">
          <div class="p-field">
            <label for="disposal_method">{{ t('assets.lifecycle.fields.disposalMethod') }}</label>
            <Dropdown id="disposal_method" v-model="form.disposal_method" :options="disposalOptions" optionLabel="label" optionValue="value" showClear class="w-full" />
          </div>
        </div>
        <div class="col-12 md:col-4">
          <div class="p-field">
            <label for="disposal_date">{{ t('assets.lifecycle.fields.disposalDate') }}</label>
            <Calendar id="disposal_date" v-model="form.disposal_date" dateFormat="dd/mm/yy" showIcon class="w-full" />
          </div>
        </div>
        <div class="col-12 md:col-4">
          <div class="p-field">
            <label for="disposal_reference">{{ t('assets.lifecycle.fields.disposalReference') }}</label>
            <InputText id="disposal_reference" v-model="form.disposal_reference" maxlength="100" class="w-full" />
          </div>
        </div>
      </div>
    </template>
  </Card>
</template>

<script setup>
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import Card from 'primevue/card'
import Calendar from 'primevue/calendar'
import Dropdown from 'primevue/dropdown'
import InputText from 'primevue/inputtext'
import InputNumber from 'primevue/inputnumber'
import AssetParentPicker from './AssetParentPicker.vue'

defineProps({
  form: { type: Object, required: true }
})

const { t } = useI18n()

const DISPOSAL_METHODS = ['scrapped', 'recycled', 'returned_to_vendor', 'sold', 'transferred', 'donated']
const disposalOptions = computed(() => DISPOSAL_METHODS.map(v => ({ value: v, label: t(`assets.lifecycle.disposalMethods.${v}`) })))

const safetyOptions = computed(() => [
  { label: t('assets.lifecycle.safety.none'), value: 'none' },
  { label: t('assets.lifecycle.safety.safetyRelated'), value: 'safety_related' },
  { label: t('assets.lifecycle.safety.safetyCritical'), value: 'safety_critical' }
])
</script>

<style scoped>
.lifecycle-group {
  margin: 0.25rem 0 0.75rem;
  font-size: 0.8rem;
  font-weight: 600;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  color: var(--sk-text-muted, #6b7a71);
}

.lifecycle-group:not(:first-child) {
  margin-top: 1rem;
  padding-top: 1rem;
  border-top: 1px solid var(--sk-border, #e1e7e3);
}

.currency-input {
  text-transform: uppercase;
}

.p-field {
  margin-bottom: 0.5rem;
}

.p-field label {
  display: block;
  margin-bottom: 0.5rem;
  font-weight: 500;
}
</style>
