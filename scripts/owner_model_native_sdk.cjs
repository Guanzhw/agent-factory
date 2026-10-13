/* Actual pinned OpenCode SDK tool loop; all HTTP is routed to a private Unix socket. */
const fs = require('node:fs')
const http = require('node:http')
const path = require('node:path')
const crypto = require('node:crypto')
const { createRequire } = require('node:module')

const fixture = JSON.parse(fs.readFileSync(0, 'utf8'))
const sdk = createRequire(path.join(fixture.sdkRoot, 'package.json'))
const compatibleEntry = sdk.resolve('@ai-sdk/openai-compatible')
const compatibleRoot = path.dirname(path.dirname(compatibleEntry))
if (JSON.parse(fs.readFileSync(path.join(compatibleRoot, 'package.json'))).version !== '2.0.41' ||
    sdk('ai/package.json').version !== '6.0.168' || sdk('zod/package.json').version !== '4.1.8') {
  throw new Error('NATIVE_SDK_VERSION_MISMATCH')
}
// OpenCode v1.18.35 applies its published error-preservation patch to this SDK.
const expectedHash = '583912405a2e17922e17708a7a90caa5e7437787d818277f8edb33a118e5e8c2'
const aiHash = '90e3e3afcef03482a72523d5b6ed0da68222cb8e75610fa9d1a75d89f2c33a8d'
if (crypto.createHash('sha256').update(fs.readFileSync(compatibleEntry)).digest('hex') !== expectedHash ||
    crypto.createHash('sha256').update(fs.readFileSync(sdk.resolve('ai'))).digest('hex') !== aiHash) {
  throw new Error('NATIVE_SDK_PATCH_PIN_MISMATCH')
}
const { createOpenAICompatible } = sdk('@ai-sdk/openai-compatible')
const { streamText, stepCountIs, tool } = sdk('ai')
const { z } = sdk('zod')
const requests = []
let toolsExecuted = 0
let nativeRequestId = 'msg_syntheticsdk0001'
globalThis.fetch = async () => { throw new Error('EXTERNAL_FETCH_FORBIDDEN') }
const model = createOpenAICompatible({ name: 'opencode-factory', apiKey: fixture.capability,
  baseURL: 'http://owner-broker.invalid/v1',
  fetch: async (url, options) => {
    if (String(url) !== 'http://owner-broker.invalid/v1/chat/completions') throw new Error('NATIVE_ROUTE_DENIED')
    const body = JSON.parse(options.body)
    requests.push(body)
    return new Promise((resolve, reject) => {
      const request = http.request({ socketPath: fixture.socket, path: '/v1/chat/completions', method: 'POST',
        headers: { ...Object.fromEntries(new Headers(options.headers)),
          'content-length': Buffer.byteLength(options.body),
          'x-opencode-session-id': 'ses_syntheticsdk0001', 'x-opencode-request': nativeRequestId } }, response => {
        const chunks = []
        response.on('data', chunk => chunks.push(chunk))
        response.on('end', () => resolve(new Response(Buffer.concat(chunks), {
          status: response.statusCode, headers: response.headers })))
      })
      request.on('error', reject)
      request.end(options.body)
    })
  } }).chatModel('owner-model')

async function main() {
  let errorCode = null
  const options = { model, stopWhen: stepCountIs(3),
    onError: ({ error }) => { errorCode = error?.data?.error?.code ?? 'NATIVE_SDK_FAILED' },
    tools: { synthetic_lookup: tool({ description: 'An inert local test lookup.',
      inputSchema: z.object({ round: z.number(), query: z.string() }),
      execute: async input => { toolsExecuted++; return { found: input.query, round: input.round } } }) } }
  let messages = [{ role: 'user', content: 'Synthetic two-round lookup.' }]
  if (fixture.scenario === 'final_then_tools') {
    const first = streamText({ model, messages, onError: options.onError })
    await first.text
    messages = [...messages, ...(await first.response).messages, { role: 'user', content: 'Now use the synthetic lookup.' }]
    nativeRequestId = 'msg_syntheticsdk0002'
  }
  const result = streamText({ ...options, messages })
  let text = ''
  try { text = await result.text } catch { errorCode ??= 'NATIVE_SDK_FAILED' }
  const normalized = requests.slice(1).map(request => request.messages.filter(message => message.role === 'assistant')
    .map(message => ({ content: message.content, arguments: message.tool_calls?.[0]?.function?.arguments,
      hasReasoning: Object.hasOwn(message, 'reasoning_content') })))
  const accepted = text === 'Synthetic native tool loop completed' &&
    toolsExecuted === (fixture.scenario === 'final_then_tools' ? 1 : 2) && requests.length === 3
  process.stdout.write(JSON.stringify({ accepted, errorCode, toolsExecuted, sdkRequests: requests.length, normalized,
    versions: { opencodeContract: '1.18.35', compatible: '2.0.41', ai: '6.0.168', zod: '4.1.8' } }) + '\n')
  process.exitCode = accepted ? 0 : 1
}
main().catch(() => { process.stdout.write(JSON.stringify({ accepted: false, errorCode: 'NATIVE_SDK_FAILED' }) + '\n'); process.exitCode = 1 })
