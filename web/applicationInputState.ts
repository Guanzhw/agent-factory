export type InputValue = null | boolean | number | string | InputValue[] | { [key: string]: InputValue };
export type ApplicationInputValues = Record<string, InputValue>;
export interface ApplicationInputSchema {
  type: 'object' | 'array' | 'string' | 'integer' | 'number' | 'boolean' | 'null';
  title?: string; description?: string;
  properties?: Record<string, ApplicationInputSchema>; required?: string[]; additionalProperties?: false;
  items?: ApplicationInputSchema; minItems?: number; maxItems?: number;
  minLength?: number; maxLength?: number; minimum?: number; maximum?: number;
  enum?: (null | boolean | number | string)[];
}
const object = (value: unknown): value is Record<string, unknown> => !!value && typeof value === 'object' && !Array.isArray(value);
const fail = () => { throw new Error('应用输入格式无法核对，请检查字段和范围。'); };
const length = (value: string) => [...value].length;
// Match the server's ensure_ascii JSON budget, including supplementary characters.
function bounded(value: unknown, maximum: number) {
  let count = 0;
  function visit(item: unknown, depth: number) {
    if (++count > 4096 || depth > 12) fail();
    if (object(item)) {
      if (Object.keys(item).length > 64 || Object.keys(item).some(key => length(key) > 100)) fail();
      Object.values(item).forEach(child => visit(child, depth + 1));
    } else if (Array.isArray(item)) {
      if (item.length > 256) fail();
      item.forEach(child => visit(child, depth + 1));
    } else if (typeof item === 'string') { if (length(item) > 16000) fail(); }
    else if (typeof item === 'number') { if (!Number.isFinite(item)) fail(); }
    else if (item !== null && typeof item !== 'boolean') fail();
  }
  visit(value, 0);
  const encoded = JSON.stringify(value).replace(/[\u007f-\uffff]/g, char => `\\u${char.charCodeAt(0).toString(16).padStart(4, '0')}`);
  // Python's default separators add spaces after each comma/colon. A conservative
  // overhead avoids accepting a near-limit value the service would reject.
  if (encoded.length + count * 2 > maximum) fail();
}
export function applicationInputSchema(value: unknown): ApplicationInputSchema {
  bounded(value, 32768); let count = 0;
  function node(raw: unknown, depth: number): void {
    if (!object(raw) || ++count > 256 || depth > 6) fail();
    const item = raw as Record<string, unknown>;
    const fields: Record<string, string[]> = { object: ['properties', 'required', 'additionalProperties'], array: ['items', 'minItems', 'maxItems'], string: ['minLength', 'maxLength', 'enum'], integer: ['minimum', 'maximum', 'enum'], number: ['minimum', 'maximum', 'enum'], boolean: ['enum'], null: ['enum'] };
    if (typeof item.type !== 'string' || !Object.hasOwn(fields, item.type) || Object.keys(item).some(key => !['type', 'title', 'description', ...fields[String(item.type)]].includes(key))) fail();
    for (const [key, max] of [['title', 120], ['description', 2000]] as const) if (item[key] !== undefined && (typeof item[key] !== 'string' || length(item[key] as string) > max)) fail();
    if (item.type === 'object') {
      if (!object(item.properties) || item.additionalProperties !== false) fail();
      const required = item.required ?? [];
      if (!Array.isArray(required) || required.some(key => typeof key !== 'string' || !Object.hasOwn(item.properties as object, key)) || new Set(required).size !== required.length) fail();
      Object.values(item.properties as object).forEach(child => node(child, depth + 1));
    } else if (item.type === 'array' || item.type === 'string') {
      const [min, max, limit] = item.type === 'array' ? ['minItems', 'maxItems', 256] as const : ['minLength', 'maxLength', 16000] as const;
      if (!Number.isSafeInteger(item[max]) || Number(item[max]) < 0 || Number(item[max]) > limit || !Number.isSafeInteger(item[min] ?? 0) || Number(item[min] ?? 0) < 0 || Number(item[min] ?? 0) > Number(item[max])) fail();
      if (item.type === 'array') node(item.items, depth + 1);
    } else if (item.type === 'integer' || item.type === 'number') {
      for (const key of ['minimum', 'maximum']) if (item[key] !== undefined && (typeof item[key] !== 'number' || !Number.isFinite(item[key]))) fail();
      if (item.minimum !== undefined && item.maximum !== undefined && Number(item.minimum) > Number(item.maximum)) fail();
    }
    if (item.enum !== undefined) {
      if (!Array.isArray(item.enum) || !item.enum.length || item.enum.length > 32 || new Set(item.enum.map(x => JSON.stringify(x))).size !== item.enum.length) fail();
      if ((item.enum as unknown[]).some(entry => entry !== null && !['boolean', 'number', 'string'].includes(typeof entry))) fail();
    }
  }
  node(value, 0); if ((value as ApplicationInputSchema).type !== 'object') fail();
  return structuredClone(value) as ApplicationInputSchema;
}
export function applicationInputValues(schema: ApplicationInputSchema, value: unknown): ApplicationInputValues {
  // Browser checks transport shape and resource bounds only. Published schema
  // semantics are validated by the server's Pydantic model, not a second engine.
  applicationInputSchema(schema); bounded(value, 65536); if (!object(value)) fail();
  return structuredClone(value) as ApplicationInputValues;
}
export function inputValuesError(schema: ApplicationInputSchema, values: unknown): string {
  try {
    const checked = applicationInputValues(schema, values);
    if (schema.required?.some(key => !Object.hasOwn(checked, key))) return '请填写标为必需的输入；字段类型与范围将在提交时由服务器核对。';
    return '';
  } catch { return '输入须为有界 JSON 对象；字段类型与范围将在提交时由服务器核对。'; }
}
export function sameApplicationInputs(left: unknown, right: unknown): boolean {
  const canonical = (value: unknown): unknown => Array.isArray(value) ? value.map(canonical) : object(value)
    ? Object.fromEntries(Object.entries(value).sort(([a], [b]) => a.localeCompare(b)).map(([key, item]) => [key, canonical(item)])) : value;
  return JSON.stringify(canonical(left)) === JSON.stringify(canonical(right));
}
