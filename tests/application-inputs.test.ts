import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import { ApplicationInputs } from '../web/ApplicationInputs.js';
import { applicationInputSchema, applicationInputValues, sameApplicationInputs } from '../web/applicationInputState.js';

const schema = () => ({ type: 'object', additionalProperties: false, required: ['question', 'count', 'confirm'], properties: {
  question: { type: 'string', title: '问题', minLength: 1, maxLength: 100 }, count: { type: 'integer', minimum: 1, maximum: 3 },
  confirm: { type: 'boolean' }, choice: { type: 'string', maxLength: 10, enum: ['a', 'b'] },
  metadata: { type: 'object', properties: { tags: { type: 'array', maxItems: 2, items: { type: 'string', maxLength: 10 } } }, additionalProperties: false },
} });
describe('bounded application inputs', () => {
  it('preserves false, empty optional values and nested inputs without defaults or mutation', () => {
    const checked = applicationInputSchema(schema()); const values = { question: '公开问题', count: 2, confirm: false, metadata: { tags: [] } };
    const result = applicationInputValues(checked, values); expect(result).toEqual(values);
    result.question = 'changed'; expect(values.question).toBe('公开问题');
    expect(sameApplicationInputs({ a: false, b: [] }, { b: [], a: false })).toBe(true);
    expect(sameApplicationInputs(undefined, {})).toBe(false);
  });
  it('rejects unknown/required fields, coercion, nonfinite numbers, enums and nested overflow', () => {
    const checked = applicationInputSchema(schema()); const values = { question: 'q', count: 2, confirm: false };
    for (const value of [{ ...values, extra: true }, { count: 2, confirm: false }, { ...values, count: '2' }, { ...values, count: 1.5 }, { ...values, count: Infinity }, { ...values, confirm: 'false' }, { ...values, choice: 'c' }, { ...values, metadata: { tags: ['a', 'b', 'c'] } }]) expect(() => applicationInputValues(checked, value)).toThrow();
  });
  it('rejects executable or unbounded schema extensions while leaving original snapshots intact', () => {
    for (const raw of [{ ...schema(), $ref: 'https://example.org' }, { ...schema(), additionalProperties: true }, { ...schema(), default: {} }, { ...schema(), properties: { text: { type: 'string' } } }, { ...schema(), properties: { files: { type: 'array', items: { type: 'string', maxLength: 10 } } } }]) expect(() => applicationInputSchema(raw)).toThrow();
    const raw = schema(); const checked = applicationInputSchema(raw); checked.required!.push('choice'); expect(raw.required).not.toContain('choice');
  });
  it('counts Unicode characters and renders controlled fields without HTML execution or implicit values', () => {
    const raw = { type: 'object', additionalProperties: false, properties: { text: { type: 'string', maxLength: 1, title: '<script>bad</script>' } } };
    expect(applicationInputValues(applicationInputSchema(raw), { text: '🧪' })).toEqual({ text: '🧪' });
    const html = renderToStaticMarkup(createElement(ApplicationInputs, { schema: raw, values: {}, onChange: () => undefined }));
    expect(html).toContain('&lt;script&gt;'); expect(html).not.toContain('<script>'); expect(html).toContain('可选');
    const invalid = renderToStaticMarkup(createElement(ApplicationInputs, { schema: { type: 'string' }, values: {}, onChange: () => undefined }));
    expect(invalid).toContain('暂不能提交'); expect(invalid).not.toContain('<input');
  });
});
