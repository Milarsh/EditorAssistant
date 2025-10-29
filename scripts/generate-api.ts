/**
 * Script for generating a typed API client from an OpenAPI schema.
 *
 * 1. Fetches the schema from SCHEMA_URL (OpenAPI JSON).
 * 2. Uses swagger-typescript-api to generate a typed API client (axios).
 * 3. Saves the result to ./src/shared/api/api.ts.
 * 4. Formats the output file with Prettier.
 *
 * Run with:
 *   yarn codegen
 */

/* eslint-disable no-console */
import { readFileSync, writeFileSync } from 'node:fs'
import { join, resolve } from 'node:path'

import { format, resolveConfig } from 'prettier'
import { generateApi, type GenerateApiParams } from 'swagger-typescript-api'

// Schema endpoint
const SCHEMA_URL = 'https://example-api.prisma-games.ru/openapi.json'
const OUTPUT_DIR = resolve(process.cwd(), './src/shared/api')
const OUTPUT_FILENAME = 'api.ts'
const OUTPUT_PATH = join(OUTPUT_DIR, OUTPUT_FILENAME)

const baseConfig: Partial<GenerateApiParams> = {
  extractEnums: true,
  output: OUTPUT_DIR,
  fileName: OUTPUT_FILENAME,
  httpClientType: 'axios',
}

const formatOutputFile = async () => {
  const text = readFileSync(OUTPUT_PATH, 'utf8')
  const options = await resolveConfig(OUTPUT_PATH)
  const formatted = await format(text, {
    ...options,
    filepath: OUTPUT_PATH,
  })

  writeFileSync(OUTPUT_PATH, formatted)
}

export const generateSwaggerApi = async () => {
  const config: GenerateApiParams = {
    ...baseConfig,
    url: SCHEMA_URL,
  }

  console.log('🚀 Generating API')
  await generateApi(config)

  console.log('🎨 Formatting output file')
  await formatOutputFile()
}

generateSwaggerApi()
