export type TenantBranding = {
  companyName: string
  logoText: string
  primaryColor: string
  primaryRgb: string
}

function subdomainFromHost(hostname: string): string | null {
  if (!hostname || hostname === 'localhost' || /^\d+\.\d+\.\d+\.\d+$/.test(hostname)) {
    return null
  }
  const parts = hostname.split('.')
  return parts.length > 2 ? parts[0].toLowerCase() : null
}

function titleFromSubdomain(subdomain: string | null): string {
  if (!subdomain) {
    return 'ITGS HR'
  }
  return subdomain
    .split('-')
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(' ')
}

export function resolveTenantBranding(hostname = window.location.hostname): TenantBranding {
  const subdomain = subdomainFromHost(hostname)
  const companyName = titleFromSubdomain(subdomain)
  const logoText = (subdomain ?? 'IT').slice(0, 2).toUpperCase()
  return {
    companyName,
    logoText,
    primaryColor: '#1A2238',
    primaryRgb: '26 34 56'
  }
}
