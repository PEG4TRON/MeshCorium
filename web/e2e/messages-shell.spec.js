import { test, expect } from '@playwright/test'

const username = process.env.MESHCORIUM_E2E_USERNAME || ''
const password = process.env.MESHCORIUM_E2E_PASSWORD || ''

test.skip(!username || !password, 'Set MESHCORIUM_E2E_USERNAME and MESHCORIUM_E2E_PASSWORD to run authenticated browser smoke tests.')

test('connect screen opens after login', async ({ page }) => {
  await page.goto('/login')
  await page.getByLabel('Имя пользователя').fill(username)
  await page.getByLabel('Пароль').fill(password)
  await page.getByRole('button', { name: 'Войти' }).click()
  await expect(page).toHaveURL(/\/$/)
  await expect(page.getByText('Добро пожаловать в MeshCorium!')).toBeVisible()
})
