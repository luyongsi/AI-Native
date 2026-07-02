#!/usr/bin/env node
/**
 * ai-task CLI — Dev Agent (A9) user-facing command-line tool.
 *
 * Provides `start`, `submit`, and `status` subcommands for
 * managing AI-powered development tasks.
 *
 * All subcommands are currently stubs that demonstrate the API contract.
 * Real implementations will wire up Context Builder, Git, and Event Bus.
 */

import { Command } from 'commander';

const program = new Command();

program
  .name('ai-task')
  .description('AI Task CLI for Dev Agent (A9) — manage AI-powered dev tasks')
  .version('0.1.0');

// ---------------------------------------------------------------------------
// Subcommand: start <taskId>
// ---------------------------------------------------------------------------
program
  .command('start <taskId>')
  .description('Fetch context from Context Builder and create a git branch')
  .action(async (taskId) => {
    const { startTask } = await import('./commands/start.js');
    await startTask(taskId);
  });

// ---------------------------------------------------------------------------
// Subcommand: submit <taskId>
// ---------------------------------------------------------------------------
program
  .command('submit <taskId>')
  .description('Stage, commit, push changes and report completion to Event Bus')
  .action(async (taskId) => {
    const { submitTask } = await import('./commands/submit.js');
    await submitTask(taskId);
  });

// ---------------------------------------------------------------------------
// Subcommand: status <taskId>
// ---------------------------------------------------------------------------
program
  .command('status <taskId>')
  .description('Show current branch and git status for a task')
  .action(async (taskId) => {
    console.log(`[ai-task] Status for task: ${taskId}`);
    console.log(`  Branch  : ai-task/${taskId}`);
    console.log(`  Status  : [STUB] Would run: git branch --show-current && git status --short`);
    console.log(`  Context : [STUB] Would query Context Builder for task context`);
  });

program.parse(process.argv);
