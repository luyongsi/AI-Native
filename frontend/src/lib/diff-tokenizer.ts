/**
 * Lightweight code tokenizer for syntax highlighting in diff views.
 * Supports TypeScript/TSX/JavaScript/JSX.
 */

interface Token {
  text: string;
  type: 'keyword' | 'string' | 'comment' | 'type' | 'function' | 'number' | 'operator' | 'plain';
}

const KEYWORDS = new Set([
  'import', 'export', 'from', 'const', 'let', 'var', 'function', 'return',
  'if', 'else', 'try', 'catch', 'finally', 'throw', 'async', 'await',
  'new', 'class', 'extends', 'implements', 'interface', 'type', 'enum',
  'default', 'void', 'null', 'undefined', 'true', 'false', 'as', 'of', 'in',
  'this', 'super', 'public', 'private', 'protected', 'readonly', 'static',
  'typeof', 'instanceof', 'yield', 'switch', 'case', 'break', 'continue',
  'for', 'while', 'do', 'get', 'set',
]);

const TYPE_KEYWORDS = new Set([
  'string', 'number', 'boolean', 'Promise', 'Array', 'Record', 'Partial',
  'Map', 'Set', 'Date', 'RegExp', 'Error', 'React', 'JSX',
  'RegionNode', 'AddressCascaderProps', 'Order', 'ExportFormat', 'ExportOptions',
  'Address', 'DownloadIcon', 'ChevronDownIcon',
]);

const TOKEN_STYLES: Record<string, string> = {
  keyword: 'text-purple-600',
  string: 'text-amber-600',
  comment: 'text-slate-400 italic',
  type: 'text-cyan-600',
  function: 'text-blue-600',
  number: 'text-emerald-600',
  operator: 'text-slate-400',
  plain: '',
};

export function tokenizeLine(line: string): Token[] {
  const tokens: Token[] = [];
  let remaining = line;

  while (remaining.length > 0) {
    // Strings (single or double quoted)
    const stringMatch = remaining.match(/^('[^']*'|"[^"]*"|`[^`]*`)/);
    if (stringMatch) {
      tokens.push({ text: stringMatch[0], type: 'string' });
      remaining = remaining.slice(stringMatch[0].length);
      continue;
    }

    // Comments
    const commentMatch = remaining.match(/^(\/\/.*)/);
    if (commentMatch) {
      tokens.push({ text: commentMatch[0], type: 'comment' });
      remaining = remaining.slice(commentMatch[0].length);
      continue;
    }

    // Operators and punctuation
    const opMatch = remaining.match(/^([{}()\[\];:,.<>]=|=>|===?|!==?|[+\-*/%&|^~]=?|\?\.?|\.{3})/);
    if (opMatch) {
      tokens.push({ text: opMatch[0], type: 'operator' });
      remaining = remaining.slice(opMatch[0].length);
      continue;
    }

    // Numbers
    const numMatch = remaining.match(/^(\d+\.?\d*)/);
    if (numMatch) {
      tokens.push({ text: numMatch[0], type: 'number' });
      remaining = remaining.slice(numMatch[0].length);
      continue;
    }

    // Words (identifiers, keywords, types)
    const wordMatch = remaining.match(/^([a-zA-Z_$][a-zA-Z0-9_$]*)/);
    if (wordMatch) {
      const word = wordMatch[0];
      if (KEYWORDS.has(word)) {
        tokens.push({ text: word, type: 'keyword' });
      } else if (TYPE_KEYWORDS.has(word)) {
        tokens.push({ text: word, type: 'type' });
      } else if (word[0] === word[0].toUpperCase()) {
        tokens.push({ text: word, type: 'type' });
      } else if (remaining.slice(word.length).trimStart().startsWith('(')) {
        tokens.push({ text: word, type: 'function' });
      } else {
        tokens.push({ text: word, type: 'plain' });
      }
      remaining = remaining.slice(word.length);
      continue;
    }

    // Whitespace and other characters
    const wsMatch = remaining.match(/^(\s+)/);
    if (wsMatch) {
      tokens.push({ text: wsMatch[0], type: 'plain' });
      remaining = remaining.slice(wsMatch[0].length);
      continue;
    }

    // Catch-all: single character
    tokens.push({ text: remaining[0], type: 'plain' });
    remaining = remaining.slice(1);
  }

  return tokens;
}

export function getTokenStyle(type: string): string {
  return TOKEN_STYLES[type] || '';
}
