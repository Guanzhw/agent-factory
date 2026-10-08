import { applicationInputSchema, inputValuesError, type ApplicationInputValues, type InputValue } from './applicationInputState.js';

export function ApplicationInputs({ schema: raw, values, onChange, disabled = false }: { schema: unknown; values: ApplicationInputValues; onChange: (values: ApplicationInputValues) => void; disabled?: boolean }) {
  let schema;
  try { schema = applicationInputSchema(raw); } catch { return <p role="alert">应用输入定义无法核对，暂不能提交此应用。</p>; }
  function change(key: string, value: InputValue | undefined) {
    const next = { ...values }; if (value === undefined) delete next[key]; else next[key] = value;
    onChange(next);
  }
  const error = inputValuesError(schema, values);
  return <fieldset disabled={disabled} aria-label="应用输入"><legend>{schema.title || '应用输入'}</legend>
    {schema.description && <p>{schema.description}</p>}
    {Object.entries(schema.properties!).map(([key, field]) => {
      const required = schema.required?.includes(key) === true;
      const value = values[key]; const label = `${field.title || key}${required ? '（必需）' : '（可选）'}`;
      return <div key={key}><label>{label}
        {field.enum ? <select aria-label={label} value={field.enum.findIndex(item => Object.is(item, value))} onChange={event => change(key, event.target.value === '-1' ? undefined : field.enum![Number(event.target.value)])}><option value={-1}>未填写</option>{field.enum.map((item, index) => <option key={index} value={index}>{String(item)}</option>)}</select>
          : field.type === 'boolean' || field.type === 'null' ? <select aria-label={label} value={value === undefined ? '' : String(value)} onChange={event => change(key, event.target.value === '' ? undefined : field.type === 'null' ? null : event.target.value === 'true')}><option value="">未填写</option>{field.type === 'null' ? <option value="null">空值</option> : <><option value="true">是</option><option value="false">否</option></>}</select>
          : field.type === 'string' ? <input aria-label={label} value={typeof value === 'string' ? value : ''} onChange={event => change(key, event.target.value)} required={required}/>
          : field.type === 'number' || field.type === 'integer' ? <input aria-label={label} type="number" step={field.type === 'integer' ? 1 : 'any'} min={field.minimum} max={field.maximum} value={typeof value === 'number' || typeof value === 'string' ? value : ''} required={required} onChange={event => change(key, event.target.value === '' ? undefined : Number(event.target.value))}/>
          : <textarea aria-label={`${label} JSON`} rows={4} value={typeof value === 'string' ? value : value === undefined ? '' : JSON.stringify(value, null, 2)} onChange={event => { const text = event.target.value; if (!text) { change(key, undefined); return; } try { change(key, JSON.parse(text) as InputValue); } catch { change(key, text); } }}/>}</label>
        {field.description && <p className="quiet">{field.description}</p>}
        {(field.type === 'object' || field.type === 'array') && <details><summary>输入结构与范围（JSON）</summary><pre>{JSON.stringify(field, null, 2)}</pre></details>}
        {!required && value !== undefined && <button type="button" className="text-button" onClick={() => change(key, undefined)}>清除{field.title || key}</button>}
      </div>;
    })}
    {error && <p role="status" className="quiet">{error}</p>}
  </fieldset>;
}
