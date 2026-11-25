// useDcim.js - shared choices and lookups of the DCIM pages (racks, device types, rack placement)
import { ref, computed } from 'vue'
import { useI18n } from 'vue-i18n'
import api from '@/api/api'
import { NETBOX_INTERFACE_TYPES, NETBOX_CABLE_TYPES, NETBOX_POE_TYPES, NETBOX_VIRTUAL_INTERFACE_TYPES, NETBOX_WIRELESS_INTERFACE_TYPES } from './dcimNetboxTypes'

export const RACK_STATUSES = ['active', 'planned', 'reserved', 'available', 'deprecated']
export const RACK_WIDTHS = [10, 19, 21, 23]
export const FACES = ['front', 'rear']
export const AIRFLOWS = ['front-to-rear', 'rear-to-front', 'left-to-right', 'right-to-left', 'side-to-rear', 'rear-to-side', 'bottom-to-top', 'top-to-bottom', 'passive', 'mixed']

// The value lists are those of NetBox (dcimNetboxTypes.js, generated from its choices.py) plus the generic ports and cables of the plant; the
// same lists as app/services/dcim_logic.py.
export const GENERIC_PORT_TYPES = ['rj45', 'sfp', 'sfp-plus', 'sfp28', 'qsfp', 'fiber-lc', 'fiber-sc', 'm12', 'usb', 'serial', 'profibus', 'canbus', 'wireless', 'virtual', 'other']
export const PORT_TYPES = [...GENERIC_PORT_TYPES, ...NETBOX_INTERFACE_TYPES.filter(t => !GENERIC_PORT_TYPES.includes(t))]
export const VIRTUAL_PORT_TYPES = [...new Set([...NETBOX_VIRTUAL_INTERFACE_TYPES, 'virtual'])]
// a cable cannot end on a virtual, wireless or channel port (NetBox NONCONNECTABLE_IFACE_TYPES)
export const NONCONNECTABLE_PORT_TYPES = [...new Set([...VIRTUAL_PORT_TYPES, ...NETBOX_WIRELESS_INTERFACE_TYPES, 'wireless', 'channel'])]
export const DUPLEXES = ['half', 'full', 'auto']
export const POE_MODES = ['pse', 'pd']
export const POE_TYPES = [...NETBOX_POE_TYPES]
export const CABLE_TYPES = [...NETBOX_CABLE_TYPES, 'serial', 'profibus', 'canbus', 'm12', 'other']
export const CABLE_STATUSES = ['connected', 'planned', 'decommissioning']
export const LENGTH_UNITS = ['km', 'm', 'cm', 'mi', 'ft', 'in']
export const RACK_AIRFLOWS = ['front-to-rear', 'rear-to-front']
export const RACK_FORM_FACTORS = ['2-post-frame', '4-post-frame', '4-post-cabinet', 'wall-frame', 'wall-frame-vertical', 'wall-cabinet', 'wall-cabinet-vertical']

export const cableStatusSeverity = status => ({ connected: 'success', planned: 'info', decommissioning: 'warning' }[status] || 'secondary')

// "1 Gbit/s", "100 Mbit/s", "10 Gbit/s": a speed in kbit/s as people say it
export function formatSpeed(kbps) {
  if (!kbps) return ''
  if (kbps >= 1000000) return `${Number((kbps / 1000000).toFixed(2))} Gbit/s`
  if (kbps >= 1000) return `${Number((kbps / 1000).toFixed(2))} Mbit/s`
  return `${kbps} kbit/s`
}

export const rackStatusSeverity = status => ({ active: 'success', planned: 'info', reserved: 'warning', available: 'info', deprecated: 'danger' }[status] || 'secondary')

// green below 70 %, orange to 90 %, red above (the same scale as the IPAM utilization bars)
export const utilizationColor = percent => (percent >= 90 ? '#dc2626' : percent >= 70 ? '#ea580c' : '#16a34a')

// "2", "1.5", "0.5": units without a trailing .0
export const formatUnits = value => (value === null || value === undefined ? '' : String(Number(value)))

// The translation key of a list value: "front-to-rear" -> "front_to_rear", "ieee802.3af" -> "ieee802_3af" (hyphens and dots break key paths)
export const keyOf = value => String(value).replace(/[-.]/g, '_')

export function useDcimChoices() {
  const { t } = useI18n()
  const options = (values, key) => computed(() => values.map(v => ({ value: v, label: t(`dcim.${key}.${keyOf(v)}`) })))
  return {
    statusOptions: options(RACK_STATUSES, 'statuses'),
    faceOptions: options(FACES, 'faces'),
    airflowOptions: options(AIRFLOWS, 'airflows'),
    rackAirflowOptions: options(RACK_AIRFLOWS, 'airflows'),
    formFactorOptions: options(RACK_FORM_FACTORS, 'formFactors'),
    widthOptions: computed(() => RACK_WIDTHS.map(w => ({ value: w, label: `${w}"` }))),
    portTypeOptions: options(PORT_TYPES, 'portTypes'),
    duplexOptions: options(DUPLEXES, 'duplexes'),
    poeModeOptions: options(POE_MODES, 'poeModes'),
    poeTypeOptions: options(POE_TYPES, 'poeTypes'),
    cableTypeOptions: options(CABLE_TYPES, 'cableTypes'),
    cableStatusOptions: options(CABLE_STATUSES, 'cableStatuses'),
    lengthUnitOptions: computed(() => LENGTH_UNITS.map(v => ({ value: v, label: v })))
  }
}

// A lazy paged list for a DataTable: fetch({ skip, limit, ...params() }) fills the table; an answer that is no longer the newest request is ignored.
// onError(err) is called when a request fails.
export function pagedList(fetch, params, onError = () => {}) {
  const items = ref([]), total = ref(0), loading = ref(false), first = ref(0), rows = ref(25), extra = ref(null)
  let request = 0
  async function load() {
    const mine = ++request
    loading.value = true
    try {
      const res = await fetch({ skip: first.value, limit: rows.value, ...params() })
      if (mine !== request) return
      items.value = res.data.items || []
      total.value = res.data.total || 0
      extra.value = res.data
    } catch (err) {
      if (mine === request) onError(err)
    } finally {
      if (mine === request) loading.value = false
    }
  }
  const reload = () => { first.value = 0; return load() }
  const onPage = event => { first.value = event.first; rows.value = event.rows; load() }
  return { items, total, loading, first, rows, extra, load, reload, onPage }
}

// Sites, locations, rack roles and manufacturers for the dropdowns of the forms; each list fills as its own answer arrives.
export function useDcimLookups() {
  const sites = ref([])
  const locations = ref([])
  const roles = ref([])
  const manufacturers = ref([])

  const listOf = r => (Array.isArray(r.data) ? r.data : (r.data?.items || []))

  function load({ manufacturers: withMakers = false } = {}) {
    const calls = [
      api.getSites().then(r => { sites.value = listOf(r).map(s => ({ value: s.id, label: s.name })) }),
      api.getLocations({ limit: 1000 }).then(r => { locations.value = listOf(r).map(l => ({ value: l.id, label: l.name, site_id: l.site_id })) }),
      api.getDcimRackRoles().then(r => { roles.value = (r.data || []).map(x => ({ value: x.id, label: x.name })) })
    ]
    if (withMakers) calls.push(api.getManufacturers().then(r => { manufacturers.value = listOf(r).map(m => ({ value: m.id, label: m.name })) }))
    return Promise.allSettled(calls)
  }

  return { sites, locations, roles, manufacturers, load }
}
