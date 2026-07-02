/**
 * Claude Code CLI runner — calls `claude` CLI to execute prompts.
 *
 * Stub implementation: simulates calling `claude --bare -p "<prompt>"`
 * and returns a mock result. Real implementation will use
 * `child_process.execFile` to invoke the Claude Code binary.
 */

/**
 * Run a Claude Code prompt.
 *
 * Real implementation (future):
 *   import { execFile } from 'node:child_process';
 *   import { promisify } from 'node:util';
 *   const execFileAsync = promisify(execFile);
 *   const { stdout } = await execFileAsync('claude', [
 *     '--bare', '-p', prompt,
 *     ...(options.model ? ['--model', options.model] : []),
 *     '--output-format', 'json',
 *   ]);
 *   return JSON.parse(stdout);
 *
 * @param {string} prompt - The prompt to send to Claude Code
 * @param {{ model?: string, bare?: boolean, outputFormat?: string, allowedTools?: string[] }} [options]
 * @returns {Promise<{ result: string, session_id: string, cost_usd: number, mock: boolean }>}
 */
export async function runClaudeCode(prompt, options = {}) {
  const {
    model = 'sonnet',
    bare = true,
    outputFormat = 'json',
    allowedTools = ['Read', 'Edit', 'Bash', 'Grep', 'Glob'],
  } = options;

  console.log(`\n[ClaudeCodeBridge] [STUB] Would execute:`);
  console.log(`  $ claude ${bare ? '--bare ' : ''}-p "${prompt.slice(0, 80)}${prompt.length > 80 ? '...' : ''}"`);
  console.log(`  --model ${model}`);
  console.log(`  --output-format ${outputFormat}`);
  console.log(`  --allowedTools ${allowedTools.join(',')}`);

  // Simulate processing time (no actual delay in stub mode)
  const mockResult = {
    summary: `[STUB] Claude Code (${model}) reviewed the changes and found no blocking issues.`,
    result: `Task completed successfully. Prompt was: "${prompt.slice(0, 60)}..."`,
    session_id: `mock-session-${Date.now().toString(36)}`,
    cost_usd: 0.12,
    mock: true,
  };

  return mockResult;
}
