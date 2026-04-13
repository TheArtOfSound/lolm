import axios from 'axios'

const api = axios.create({
  baseURL: '/api',
  timeout: 30000,
})

// Auth interceptor
api.interceptors.request.use((config) => {
  const password = localStorage.getItem('lolm_password') || ''
  if (password) {
    config.headers['X-API-Key'] = password
  }
  return config
})

// Retry on cold starts (Render spins down after inactivity)
api.interceptors.response.use(undefined, async (error) => {
  const config = error.config
  if (!config || config._retryCount >= 3) return Promise.reject(error)
  config._retryCount = (config._retryCount || 0) + 1
  await new Promise(r => setTimeout(r, 2000))
  return api(config)
})

export default api
