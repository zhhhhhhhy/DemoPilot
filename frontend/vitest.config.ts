import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vitest/config'

export default defineConfig({
  plugins: [vue()],
  test: {
    environment: 'jsdom',
    fileParallelism: false,
    maxWorkers: 1,
    // Keep unit tests in one worker thread; avoids Windows fork startup stalls.
    pool: 'threads',
    setupFiles: ['./src/test/setup.ts'],
  },
})
