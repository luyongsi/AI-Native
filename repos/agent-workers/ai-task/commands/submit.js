/**
 * ai-task submit command — stages, commits, pushes changes and reports
 * completion to the Event Bus.
 *
 * Stub implementation. Real version will:
 *   1. Run `git add -A`
 *   2. Run `git commit -m "ai-task: {taskId}"`
 *   3. Run `git push`
 *   4. HTTP POST to Event Bus to report completion
 */

import { runClaudeCode } from '../lib/claude-runner.js';

/**
 * @param {string} taskId
 */
export async function submitTask(taskId) {
  console.log(`\n[ai-task] Submitting task: ${taskId}`);

  // ------------------------------------------------------------------
  // Simulate git add -A
  // ------------------------------------------------------------------
  console.log(`\n[ai-task] [STUB] Would run: git add -A`);
  console.log(`  Staging all changes in working directory ...`);

  // ------------------------------------------------------------------
  // Simulate git commit
  // ------------------------------------------------------------------
  const commitMessage = `ai-task: ${taskId}`;
  console.log(`\n[ai-task] [STUB] Would run: git commit -m "${commitMessage}"`);

  // ------------------------------------------------------------------
  // Simulate diff summary
  // ------------------------------------------------------------------
  console.log(`\n  ┌─────────────────────────────────────────────┐`);
  console.log(`  │  Diff Summary                               │`);
  console.log(`  ├─────────────────────────────────────────────┤`);
  console.log(`  │  Files created  : 3                         │`);
  console.log(`  │  Files modified : 1                         │`);
  console.log(`  │  Lines added    : +127                      │`);
  console.log(`  │  Lines removed  : -8                        │`);
  console.log(`  └─────────────────────────────────────────────┘`);

  // ------------------------------------------------------------------
  // Simulate git push
  // ------------------------------------------------------------------
  const branchName = `ai-task/${taskId}`;
  console.log(`\n[ai-task] [STUB] Would run: git push origin ${branchName}`);

  // ------------------------------------------------------------------
  // Simulate Event Bus report
  // ------------------------------------------------------------------
  console.log(`\n[ai-task] [STUB] Would POST to Event Bus:`);
  console.log(`  URL    : http://localhost:8000/api/events`);
  console.log(`  Event  : task.completed`);
  console.log(`  Payload: { "taskId": "${taskId}", "status": "submitted", "branch": "${branchName}" }`);

  // ------------------------------------------------------------------
  // Optional: simulate running Claude Code for pre-submit review
  // ------------------------------------------------------------------
  console.log(`\n[ai-task] [STUB] Running pre-submit Claude Code review ...`);
  const review = await runClaudeCode(
    `Review the changes on branch ${branchName} for obvious issues before submitting.`,
    { model: 'sonnet', bare: true }
  );
  console.log(`  Review result: ${review.summary}`);

  console.log(`\n[ai-task] Task "${taskId}" submitted successfully (stub mode).`);
  console.log(`  Real submission would push to remote and notify Event Bus.\n`);
}
