import { readFileSync, readdirSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
import ts from 'typescript';

const root = resolve(import.meta.dirname, '..');
const source = (path: string) => readFileSync(resolve(root, path), 'utf8');

/** Keep the concrete deployment root explicit; the public frontend cannot import an application. */
describe('frontend application source boundary', () => {
  it('permits application imports only in the static composition entry', () => {
    const violations: string[] = [];
    for (const name of readdirSync(resolve(root, 'web')).filter(name => /\.tsx?$/.test(name) && name !== 'composition.tsx')) {
      const path = resolve(root, 'web', name);
      const ast = ts.createSourceFile(path, readFileSync(path, 'utf8'), ts.ScriptTarget.Latest, true);
      function visit(node: ts.Node) {
        const specifier = ts.isImportDeclaration(node) || ts.isExportDeclaration(node) ? node.moduleSpecifier
          : ts.isCallExpression(node) && node.expression.kind === ts.SyntaxKind.ImportKeyword ? node.arguments[0] : undefined;
        if (specifier && ts.isStringLiteral(specifier) && resolve(dirname(path), specifier.text).startsWith(resolve(root, 'apps') + '/')) violations.push(`${name}: ${specifier.text}`);
        ts.forEachChild(node, visit);
      }
      visit(ast);
    }
    expect(violations).toEqual([]);
  });

  it('keeps research routes and runtime-specific task rendering out of the shell and public API', () => {
    for (const path of ['web/App.tsx', 'web/workspaceNavigation.ts', 'web/api.ts', 'web/TaskWorkspace.tsx']) {
      expect(source(path), path).not.toMatch(/OpenResearchWorkspace|AutoResearch|\/autoresearch|\/synthesis|\/comparisons|orx_experiment_run|personalAgentApi/);
    }
    expect(source('web/ApplicationComposer.tsx')).not.toContain('source-grounded-synthesis-fixture-v1');
    expect(source('web/main.tsx')).toContain("'./composition.js'");
  });

  it('does not add dynamic discovery to static application composition', () => {
    expect(source('web/composition.tsx')).toContain("'../apps/research/web/ResearchPages.js'");
    expect(source('web/composition.tsx')).not.toMatch(/import\.meta\.glob|import\(/);
  });
});
