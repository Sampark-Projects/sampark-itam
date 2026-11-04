// Configurazione dell'applicazione
import packageJson from '../../package.json'

export const appConfig = {
  // Versione dell'applicazione (allineata a package.json)
  version: packageJson.version,
  
  // Nome dell'applicazione
  name: 'Sampark',
  
  // Descrizione
  description: 'Configuration Management Database for Industrial Control Systems',
  
  // Informazioni sul copyright
  copyright: {
    company: 'Sampark',
    url: 'https://www.samparksoftwares.com'
  },
  
  // Link utili
  links: {
    website: 'https://www.samparksoftwares.com',
    github: 'https://github.com/Sampark-Projects/sampark-itam',
    issues: 'https://github.com/Sampark-Projects/sampark-itam/issues',
    license: 'https://github.com/Sampark-Projects/sampark-itam/blob/main/LICENSE'
  },
  
  // Configurazione API
  api: {
    baseUrl: '/api',
    timeout: 30000
  },
  
  // Configurazione paginazione
  pagination: {
    defaultPageSize: 25,
    pageSizeOptions: [10, 25, 50, 100]
  },
  
  // Configurazione upload
  upload: {
    maxFileSize: 10 * 1024 * 1024, // 10MB
    allowedTypes: ['image/*', 'application/pdf', 'application/msword', 'application/vnd.openxmlformats-officedocument.wordprocessingml.document']
  }
}

export default appConfig 