import type { FactoryApplication } from './models.js';

function submittedFieldsMatch(expected: unknown, actual: unknown): boolean {
  if (Array.isArray(expected)) return Array.isArray(actual) && expected.length === actual.length && expected.every((value, index) => submittedFieldsMatch(value, actual[index]));
  if (expected && typeof expected === 'object') return !!actual && typeof actual === 'object' && !Array.isArray(actual)
    && Object.entries(expected).every(([key, value]) => Object.hasOwn(actual, key) && submittedFieldsMatch(value, (actual as Record<string, unknown>)[key]));
  return Object.is(expected, actual);
}
/** Only accept the submitted definition and its intended lineage; server defaults may fill omitted fields. */
export function savedApplicationMatches(body: Record<string, unknown>, parent: FactoryApplication | undefined, saved: FactoryApplication): boolean {
  if (!saved || typeof saved.id !== 'string' || !/^[A-Za-z0-9_.:-]{1,100}$/.test(saved.id)
      || !Number.isSafeInteger(saved.version) || saved.version < 1 || typeof saved.sha256 !== 'string' || !/^[a-f0-9]{64}$/.test(saved.sha256)) return false;
  const expected = { ...body };
  if (expected.id === null) delete expected.id;
  if (!submittedFieldsMatch(expected, saved)) return false;
  if (parent && (saved.id !== parent.id || saved.version <= parent.version)) return false;
  if (!parent && !body.id && saved.version !== 1) return false;
  const modes = body.modes;
  return !!modes && typeof modes === 'object' && !Array.isArray(modes)
    && Object.keys(modes).length === Object.keys(saved.modes).length;
}
