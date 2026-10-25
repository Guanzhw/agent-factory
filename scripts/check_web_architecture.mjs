/** Static frontend boundaries from an explicit map; never executes project code.
 * Uses one selected tsconfig and syntax-level imports/re-exports/require calls.
 * Custom loader aliases and eval are outside this check; bundler glob discovery
 * is rejected as a coverage gap; external package implementations and non-code assets are not walked.
 */
import { existsSync, readFileSync, readdirSync, realpathSync, statSync } from 'node:fs';
import { isBuiltin } from 'node:module';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import { parseArgs } from 'node:util';
import ts from 'typescript';

const sourceExtension = /\.(?:[cm]?[jt]s|[jt]sx)$/i;
const assetExtension = /\.(?:json|css|scss|sass|less|svg|png|jpe?g|gif|webp|ico|woff2?|ttf|eot|mp[34]|webm|wav)$/i;
const within = (file, directory) => file === directory || file.startsWith(directory + '/');
const diagnosticText = diagnostic => ts.flattenDiagnosticMessageText(diagnostic.messageText, '\n');

function projectPath(root, value) {
  if (typeof value !== 'string' || !value || path.isAbsolute(value) || /[*?]/.test(value)) {
    throw new Error(`Use an exact project-relative path: ${String(value)}`);
  }
  const relative = path.relative(root, path.resolve(root, value)).split(path.sep).join('/');
  if (relative === '..' || relative.startsWith('../')) throw new Error(`Path leaves the project: ${value}`);
  return relative || '.';
}

function readModules(root, roots) {
  if (!Array.isArray(roots) || !roots.length) throw new Error('Declare nonempty source_roots');
  const modules = new Map();
  function visit(directory) {
    for (const entry of readdirSync(directory, { withFileTypes: true }).sort((a, b) => a.name.localeCompare(b.name))) {
      const filename = path.join(directory, entry.name);
      if (entry.isDirectory() && !['node_modules', '.git'].includes(entry.name)) visit(filename);
      else if (entry.isFile() && sourceExtension.test(entry.name)) {
        const id = path.relative(root, filename).split(path.sep).join('/');
        modules.set(id, { filename, tree: ts.createSourceFile(filename, readFileSync(filename, 'utf8'), ts.ScriptTarget.Latest, true) });
      }
    }
  }
  for (const source of roots) {
    const directory = path.resolve(root, projectPath(root, source));
    if (!existsSync(directory) || !statSync(directory).isDirectory()) throw new Error(`Missing source directory: ${source}`);
    projectPath(root, path.relative(root, realpathSync(directory)) || '.');
    visit(directory);
  }
  return modules;
}

function compilerOptions(root, config) {
  const filename = path.resolve(root, projectPath(root, config.tsconfig ?? 'tsconfig.json'));
  const loaded = ts.readConfigFile(filename, ts.sys.readFile);
  if (loaded.error) throw new Error(diagnosticText(loaded.error));
  const parsed = ts.parseJsonConfigFileContent(loaded.config, ts.sys, path.dirname(filename), {}, filename);
  if (parsed.errors.length) throw new Error(parsed.errors.map(diagnosticText).join('\n'));
  return parsed.options;
}

function ownershipMap(root, config, modules) {
  if (!Array.isArray(config.core) || !config.core.length || !config.apps || typeof config.apps !== 'object'
      || Array.isArray(config.apps)) {
    throw new Error('Declare nonempty core ownership and an apps map (which may be empty)');
  }
  const contains = (file, prefix) => prefix === '.' || within(file, prefix);
  function checkedPrefix(value) {
    const prefix = projectPath(root, value);
    if (![...modules.keys()].some(file => contains(file, prefix))) throw new Error(`Ownership path has no source files: ${value}`);
    return prefix;
  }
  const core = config.core.map(checkedPrefix);
  const apps = Object.entries(config.apps).map(([name, app]) => {
    if (!app || typeof app !== 'object' || (app.public !== undefined && !Array.isArray(app.public))) throw new Error(`Invalid application map: ${name}`);
    const prefix = checkedPrefix(app.path);
    const publicFiles = new Set((app.public ?? []).map(value => projectPath(root, value)));
    for (const file of publicFiles) {
      if (!modules.has(file) || !contains(file, prefix)) throw new Error(`Public API must name an exact source file owned by ${name}: ${file}`);
    }
    return { name, prefix, publicFiles };
  });
  for (let index = 0; index < apps.length; index++) {
    const app = apps[index];
    if (core.some(prefix => contains(prefix, app.prefix))) throw new Error(`Application ownership cannot replace core: ${app.prefix}`);
    if (apps.slice(index + 1).some(other => contains(app.prefix, other.prefix) || contains(other.prefix, app.prefix))) {
      throw new Error(`Overlapping application ownership: ${app.prefix}`);
    }
  }
  if (config.composition_roots !== undefined && !Array.isArray(config.composition_roots)) throw new Error('composition_roots must be an array');
  const composition = new Set((config.composition_roots ?? []).map(value => projectPath(root, value)));
  for (const file of composition) if (!modules.has(file)) throw new Error(`Composition root must name one exact source file: ${file}`);
  const owner = file => apps.find(app => contains(file, app.prefix));
  const isCore = file => !composition.has(file) && !owner(file) && core.some(prefix => contains(file, prefix));
  if (![...modules.keys()].some(isCore)) throw new Error('The map must leave actual core files to check');
  return { composition, owner, isCore };
}

function dependencyGraph(root, modules, options) {
  const graph = new Map(), gaps = [];
  const cache = ts.createModuleResolutionCache(root, filename => filename, options);
  for (const [id, module] of modules) {
    module.tree.impliedNodeFormat = ts.getImpliedNodeFormatForFile(module.filename, undefined, ts.sys, options);
    const edges = new Map();
    const line = node => module.tree.getLineAndCharacterOfPosition(node.getStart(module.tree)).line + 1;
    const gap = (node, message) => gaps.push({ module: id, line: line(node), message });
    for (const diagnostic of module.tree.parseDiagnostics) {
      gaps.push({ module: id, line: module.tree.getLineAndCharacterOfPosition(diagnostic.start ?? 0).line + 1,
        message: 'Cannot parse source: ' + diagnosticText(diagnostic) });
    }
    function add(specifier, node) {
      if (!specifier || !(ts.isStringLiteral(specifier) || ts.isNoSubstitutionTemplateLiteral(specifier))) {
        gap(node, 'Unresolved dynamic dependency; use a literal import or an explicit statically imported registration');
        return;
      }
      const value = specifier.text;
      const mode = ts.getModeForUsageLocation(module.tree, specifier, options);
      const result = ts.resolveModuleName(value, module.filename, options, ts.sys, cache, undefined, mode).resolvedModule;
      if (!result) {
        if (!isBuiltin(value) && !assetExtension.test(value)) gap(node, `Cannot resolve dependency ${JSON.stringify(value)} with the selected tsconfig`);
        return;
      }
      const target = path.relative(root, path.resolve(result.resolvedFileName)).split(path.sep).join('/');
      if (modules.has(target)) {
        if (target !== id && !edges.has(target)) edges.set(target, { target, line: line(node) });
      } else if (!result.isExternalLibraryImport && !result.resolvedFileName.split(path.sep).includes('node_modules')
                 && sourceExtension.test(result.resolvedFileName)) {
        gap(node, `Resolved local source is outside source_roots: ${target}`);
      }
    }
    function shadowedRequire(node) {
      for (let parent = node.parent; parent; parent = parent.parent) {
        if (ts.isFunctionLike(parent) && parent.parameters?.some(parameter => ts.isIdentifier(parameter.name) && parameter.name.text === 'require')) return true;
      }
      return false;
    }
    function visit(node) {
      if ((ts.isPropertyAccessExpression(node) || ts.isElementAccessExpression(node))
          && ts.isMetaProperty(node.expression) && node.expression.keywordToken === ts.SyntaxKind.ImportKeyword
          && (ts.isPropertyAccessExpression(node) ? /^glob(?:Eager)?$/.test(node.name.text)
            : node.argumentExpression && ts.isStringLiteral(node.argumentExpression) && /^glob(?:Eager)?$/.test(node.argumentExpression.text))) {
        gap(node, 'Bundler glob discovery is not statically resolved; use explicit imports for application registration');
      } else if (ts.isImportDeclaration(node) || ts.isExportDeclaration(node)) {
        if (node.moduleSpecifier) add(node.moduleSpecifier, node);
      } else if (ts.isImportEqualsDeclaration(node) && ts.isExternalModuleReference(node.moduleReference)) {
        add(node.moduleReference.expression, node);
      } else if (ts.isImportTypeNode(node)) {
        add(ts.isLiteralTypeNode(node.argument) ? node.argument.literal : undefined, node);
      } else if (ts.isCallExpression(node)) {
        if (node.expression.kind === ts.SyntaxKind.ImportKeyword) add(node.arguments[0], node);
        else if (ts.isIdentifier(node.expression) && node.expression.text === 'require' && !shadowedRequire(node)) add(node.arguments[0], node);
      }
      ts.forEachChild(node, visit);
    }
    visit(module.tree);
    graph.set(id, [...edges.values()].sort((a, b) => a.target.localeCompare(b.target)));
  }
  return { graph, gaps };
}

/** Paths in core/apps are directory prefixes; public/composition entries are exact files. */
export function checkArchitecture(projectRoot, config) {
  const root = path.resolve(projectRoot);
  const modules = readModules(root, config.source_roots);
  const { composition, owner, isCore } = ownershipMap(root, config, modules);
  const { graph, gaps: allGaps } = dependencyGraph(root, modules, compilerOptions(root, config));
  const violations = [], covered = new Set();
  for (const source of [...modules.keys()].sort()) {
    const sourceApp = owner(source), sourceCore = isCore(source), sourceComposition = composition.has(source);
    if (!sourceApp && !sourceCore && !sourceComposition) continue;
    const queue = [[source, [source]]], visited = new Set([source]);
    for (let index = 0; index < queue.length; index++) {
      const [current, chain] = queue[index];
      for (const { target } of graph.get(current)) {
        if (visited.has(target)) continue;
        visited.add(target);
        const targetApp = owner(target), next = [...chain, target];
        let reason;
        if (composition.has(target) && !sourceComposition) reason = 'Core/apps cannot import the composition root; inject a shared port instead';
        else if (sourceCore && targetApp) reason = 'Core reaches application code; move application wiring to the exact composition root';
        else if (targetApp && !sourceComposition && targetApp !== sourceApp) {
          if (targetApp.publicFiles.has(target)) continue; // This app API is independently checked as an origin.
          reason = 'Cross-app private implementation; use an exact declared public entry or move shared behavior to a helper';
        }
        if (reason) violations.push({ chain: next, reason });
        else queue.push([target, next]);
      }
    }
    for (const file of visited) covered.add(file);
  }
  const gaps = allGaps.filter(gap => covered.has(gap.module)).sort((a, b) => a.module.localeCompare(b.module) || a.line - b.line);
  return { modules, graph, violations, gaps, covered, accepted: !violations.length && !gaps.length };
}

export function main(argv = process.argv.slice(2)) {
  try {
    const { values } = parseArgs({ args: argv, options: { root: { type: 'string', default: process.cwd() }, config: { type: 'string' } } });
    if (!values.config) throw new Error('--config is required; no repository boundary map is assumed');
    const result = checkArchitecture(values.root, JSON.parse(readFileSync(values.config, 'utf8')));
    for (const violation of result.violations) {
      console.error(violation.chain.join(' -> '));
      for (let index = 0; index < violation.chain.length - 1; index++) {
        const source = violation.chain[index], target = violation.chain[index + 1];
        console.error(`  ${source}:${result.graph.get(source).find(edge => edge.target === target).line} -> ${target}`);
      }
      console.error(`  Fix: ${violation.reason}`);
    }
    for (const gap of result.gaps) console.error(`Coverage gap: ${gap.module}:${gap.line}: ${gap.message}`);
    console.log(JSON.stringify({ modules: result.modules.size, protectedReachableFiles: result.covered.size,
      violations: result.violations.length, coverageGaps: result.gaps.length, accepted: result.accepted }));
    return result.accepted ? 0 : 1;
  } catch (error) {
    console.error(`Architecture configuration/parse error: ${error.message}`);
    return 2;
  }
}

if (process.argv[1] && pathToFileURL(path.resolve(process.argv[1])).href === import.meta.url) process.exitCode = main();
