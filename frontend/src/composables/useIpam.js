// useIpam.js - shared choices and lookups of the IPAM pages
import { ref, computed } from 'vue'
import { useI18n } from 'vue-i18n'
import api from '@/api/api'

export const PREFIX_STATUSES = ['container', 'active', 'reserved', 'deprecated']
export const RANGE_STATUSES = ['active', 'reserved', 'deprecated']
export const VLAN_STATUSES = ['active', 'reserved', 'deprecated']
export const IP_STATUSES = ['active', 'reserved', 'deprecated', 'dhcp', 'slaac']
export const IP_ROLES = ['loopback', 'secondary', 'anycast', 'vip', 'vrrp', 'hsrp', 'glbp', 'carp']

export const FHRP_PROTOCOLS = ['vrrp2', 'vrrp3', 'hsrp', 'glbp', 'carp', 'clusterxl', 'other']
export const FHRP_AUTH_TYPES = ['plaintext', 'md5']
export const INTERFACE_VLAN_MODES = ['access', 'tagged', 'tagged-all', 'q-in-q']

export const statusSeverity = status => ({ active: 'success', container: 'info', reserved: 'warning', deprecated: 'danger', dhcp: 'info', slaac: 'info' }[status] || 'secondary')

// green below 70 %, orange to 90 %, red above
export const utilizationColor = percent => (percent >= 90 ? '#dc2626' : percent >= 70 ? '#ea580c' : '#16a34a')

export function useIpamChoices() {
  const { t } = useI18n()
  const options = (values, key) => computed(() => values.map(v => ({ value: v, label: t(`ipam.${key}.${v}`) })))
  return {
    prefixStatusOptions: options(PREFIX_STATUSES, 'statuses'),
    rangeStatusOptions: options(RANGE_STATUSES, 'statuses'),
    vlanStatusOptions: options(VLAN_STATUSES, 'statuses'),
    ipStatusOptions: options(IP_STATUSES, 'statuses'),
    ipRoleOptions: options(IP_ROLES, 'ipRoles'),
    familyOptions: computed(() => [{ value: 4, label: 'IPv4' }, { value: 6, label: 'IPv6' }])
  }
}

// VRFs, roles, VLANs and sites for the dropdowns of the forms; loaded once per page.
export function useIpamLookups() {
  const vrfs = ref([])
  const roles = ref([])
  const vlans = ref([])
  const sites = ref([])
  const locations = ref([])

  async function load({ vlan = false } = {}) {
    const calls = [
      api.getIpamVrfs({ limit: 500 }).then(r => { vrfs.value = (r.data.items || []).map(v => ({ value: v.id, label: v.rd ? `${v.name} (${v.rd})` : v.name })) }),
      api.getIpamRoles().then(r => { roles.value = (r.data || []).map(v => ({ value: v.id, label: v.name })) }),
      api.getSites().then(r => {
        const list = Array.isArray(r.data) ? r.data : (r.data?.items || [])
        sites.value = list.map(s => ({ value: s.id, label: s.name }))
      })
    ]
    calls.push(api.getLocations({ limit: 1000 }).then(r => {
      const list = Array.isArray(r.data) ? r.data : (r.data?.items || [])
      locations.value = list.map(l => ({ value: l.id, label: l.name, site_id: l.site_id }))
    }))
    if (vlan) calls.push(api.getIpamVlans({ limit: 500 }).then(r => { vlans.value = (r.data.items || []).map(v => ({ value: v.id, label: v.label })) }))
    await Promise.allSettled(calls)
  }

  return { vrfs, roles, vlans, sites, locations, load }
}
