import type { FactoryMaterial, MaterialReference } from './models.js';

export const materialKinds = ['skill', 'tool', 'prompt', 'knowledge', 'model', 'environment'] as const;
export const exactMaterialKey = (ref: MaterialReference) => JSON.stringify([ref.id, ref.version, ref.sha256]);
export const materialReference = ({ id, version, sha256 }: MaterialReference): MaterialReference => ({ id, version, sha256 });
export const selectableMaterial = (material: FactoryMaterial) => material.published && !material.archived
  && (!material.governance || material.governance.state === 'published');
export function catalogMaterials(materials: FactoryMaterial[], query = '', kind?: FactoryMaterial['kind']) {
  const search = query.trim().toLocaleLowerCase();
  const seen = new Set<string>();
  return materials.filter(material => {
    const key = exactMaterialKey(material);
    if (seen.has(key) || !selectableMaterial(material) || (kind && material.kind !== kind)
      || (search && ![material.id, material.name, material.description].some(text => text.toLocaleLowerCase().includes(search)))) return false;
    seen.add(key); return true;
  });
}
export function selectionIssues(materials: FactoryMaterial[], selected: MaterialReference[]) {
  const available = new Map(materials.map(material => [exactMaterialKey(material), material]));
  const selectedKeys = new Set(selected.map(exactMaterialKey));
  return selected.map(ref => {
    const material = available.get(exactMaterialKey(ref));
    return { ref, material, unavailable: !material || !selectableMaterial(material),
      missingDependencies: material?.dependencies.filter(dependency => !selectedKeys.has(exactMaterialKey(dependency))) ?? [] };
  });
}
export function toggleMaterialSelection(selected: MaterialReference[], material: FactoryMaterial, checked: boolean): MaterialReference[] {
  const key = exactMaterialKey(material);
  if (!checked) return selected.filter(ref => exactMaterialKey(ref) !== key).map(materialReference);
  if (!selectableMaterial(material) || selected.some(ref => exactMaterialKey(ref) === key)) return selected.map(materialReference);
  return [...selected.map(materialReference), materialReference(material)];
}
export function runtimeBindingSummary(material: FactoryMaterial): string {
  const binding: unknown = (material as FactoryMaterial & { runtimeBinding?: unknown }).runtimeBinding;
  if (!binding || typeof binding !== 'object' || Array.isArray(binding)) return '未声明注册运行绑定；以服务端预检为准';
  const record = binding as Record<string, unknown>;
  return typeof record.adapterId === 'string' && typeof record.revision === 'string'
    ? `${record.adapterId} · ${record.revision}` : '绑定摘要不可用；以服务端预检为准';
}
