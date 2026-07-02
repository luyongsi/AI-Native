/**
 * ai-task start command — fetches context and creates a git branch.
 *
 * Stub implementation. Real version will:
 *   1. Call Context Builder API (GET /api/context/{taskId})
 *   2. Create a git branch named ai-task/{taskId}
 *   3. Print a summary of loaded context
 */

import { fetchContext } from '../lib/context-fetcher.js';

/**
 * @param {string} taskId
 */
export async function startTask(taskId) {
  console.log(`\n[ai-task] Starting task: ${taskId}`);
  console.log(`[ai-task] [STUB] Fetching context from Context Builder ...`);

  // ------------------------------------------------------------------
  // Simulate Context Builder API call
  // ------------------------------------------------------------------
  const context = await fetchContext(taskId);

  // ------------------------------------------------------------------
  // Print context summary table
  // ------------------------------------------------------------------
  console.log(`\n  ┌─────────────────────────────────────────────┐`);
  console.log(`  │  Context Loaded for ${taskId.padEnd(28)}│`);
  console.log(`  ├─────────────────────────────────────────────┤`);
  console.log(`  │  Domain      : ${(context.domain || 'general').padEnd(28)}│`);
  console.log(`  │  API Paths   : ${String(context.api_paths || 0).padEnd(28)}│`);
  console.log(`  │  DB Tables   : ${String(context.db_tables || 0).padEnd(28)}│`);
  console.log(`  │  Spec Version: ${(context.spec_version || '0.1.0').padEnd(28)}│`);
  console.log(`  │  Requirements: ${String(context.requirements_count || 0).padEnd(28)}│`);
  console.log(`  └─────────────────────────────────────────────┘`);

  // ------------------------------------------------------------------
  // Simulate git branch creation
  // ------------------------------------------------------------------
  const branchName = `ai-task/${taskId}`;
  console.log(`\n[ai-task] [STUB] Would run:`);
  console.log(`  $ git checkout -b ${branchName}`);
  console.log(`  $ git push -u origin ${branchName}`);

  // ------------------------------------------------------------------
  // Print instructions for the developer
  // ------------------------------------------------------------------
  console.log(`\n[ai-task] Task "${taskId}" is ready. Next steps:`);
  console.log(`  1. Edit files as needed`);
  console.log(`  2. Run \`ai-task submit ${taskId}\` when done`);
  console.log(`  3. Or run \`ai-task status ${taskId}\` to check progress\n`);
}
