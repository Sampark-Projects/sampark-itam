// Money and API-error helpers shared by the lifecycle screens.

// 1250.5, "INR" -> "₹1,250.50" ; an unknown currency code falls back to "1,250.5 XYZ"
export function formatMoney(amount, currency) {
  if (amount === null || amount === undefined || amount === '') return ''
  const value = Number(amount)
  if (Number.isNaN(value)) return ''
  if (currency) {
    try {
      return new Intl.NumberFormat('en-IN', { style: 'currency', currency }).format(value)
    } catch (e) {
      // not an ISO currency code: show the plain number and the code
    }
  }
  return new Intl.NumberFormat('en-IN', { maximumFractionDigits: 2 }).format(value) + (currency ? ` ${currency}` : '')
}

// Text for a failed API call: the translated error code when there is one, plus the server detail
export function apiErrorText(err, t) {
  const data = err?.response?.data || {}
  const code = data.error_code
  const translated = code ? t(`core.${code}`) : ''
  const base = translated && translated !== `core.${code}` ? translated : t('core.generic')
  const detail = data.message || data.detail
  let extra = ''
  if (Array.isArray(detail)) extra = detail.map(d => d.msg).join('; ')
  else if (typeof detail === 'string' && detail !== code) extra = detail
  return `${base} ${extra}`.trim()
}

// Rows -> CSV text (quotes and commas escaped, starts with a BOM so Excel reads UTF-8)
export function toCsv(headers, rows) {
  const esc = (v) => {
    const s = v === null || v === undefined ? '' : String(v)
    return /[",\n\r]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s
  }
  return '﻿' + [headers, ...rows].map(r => r.map(esc).join(',')).join('\r\n')
}

export function downloadText(filename, text, type = 'text/csv;charset=utf-8') {
  const url = URL.createObjectURL(new Blob([text], { type }))
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}
