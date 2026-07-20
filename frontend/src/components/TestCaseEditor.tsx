'use client';

import React, { useState, useEffect } from 'react';
import { useActivityStream } from '@/hooks/useActivityStream';
import ActivityStream from '@/components/ActivityStream';

interface TestStep {
  step_number: number;
  action: string;
  expected: string;
}

interface TestCase {
  id: string;
  req_id: string;
  title: string;
  description?: string;
  steps: TestStep[];
  preconditions?: string;
  priority: string;
  status: string;
  tags: string[];
  validation_status: string;
  validation_errors?: Record<string, any>;
  coverage_info?: Record<string, any>;
  source: string;
  augmentation_suggestions?: any[];
  created_at: string;
  updated_at: string;
}

interface TestCaseEditorProps {
  reqId: string;
  onClose?: () => void;
}

const statusBadgeClasses: Record<string, string> = {
  pending: 'bg-amber-100 text-amber-800 border-amber-300',
  passed: 'bg-emerald-100 text-emerald-800 border-emerald-300',
  failed: 'bg-red-100 text-red-800 border-red-300',
  draft: 'bg-slate-700 text-slate-200 border-slate-300',
};

const priorityColors: Record<string, string> = {
  P0: 'text-red-600 bg-red-50',
  P1: 'text-orange-600 bg-orange-50',
  P2: 'text-yellow-600 bg-yellow-50',
  P3: 'text-slate-400 bg-slate-800/50',
};

function TestCaseListItem({ testCase, onEdit, onValidate }: { testCase: TestCase; onEdit: (tc: TestCase) => void; onValidate: (id: string) => void }) {
  return (
    <div className="p-4 border border-slate-700 rounded-lg hover:shadow-md transition-shadow">
      <div className="flex items-start justify-between gap-4">
        <div className="flex-1">
          <h3 className="font-semibold text-slate-100 mb-1">{testCase.title}</h3>
          {testCase.description && <p className="text-sm text-slate-400 mb-2">{testCase.description}</p>}
          <div className="flex items-center gap-2 mb-2">
            <span className={`text-xs px-2 py-1 rounded border ${statusBadgeClasses[testCase.validation_status] || statusBadgeClasses.pending}`}>
              {testCase.validation_status}
            </span>
            <span className={`text-xs px-2 py-1 rounded ${priorityColors[testCase.priority] || priorityColors.P2}`}>
              {testCase.priority}
            </span>
            {testCase.source && (
              <span className="text-xs px-2 py-1 bg-blue-50 text-blue-700 rounded">
                {testCase.source}
              </span>
            )}
          </div>
          <div className="text-xs text-slate-400">
            {testCase.steps.length} steps • Updated {new Date(testCase.updated_at).toLocaleDateString()}
          </div>
        </div>
        <div className="flex gap-2">
          <button
            onClick={() => onValidate(testCase.id)}
            className="px-3 py-1 text-sm bg-blue-100 hover:bg-blue-200 text-blue-700 rounded border border-blue-300 transition-colors"
          >
            Validate
          </button>
          <button
            onClick={() => onEdit(testCase)}
            className="px-3 py-1 text-sm bg-slate-700 hover:bg-slate-600 text-slate-600 rounded border border-slate-300 transition-colors"
          >
            Edit
          </button>
        </div>
      </div>
    </div>
  );
}

function TestCaseModal({
  testCase,
  onSave,
  onClose,
}: {
  testCase: TestCase | null;
  onSave: (tc: TestCase) => Promise<void>;
  onClose: () => void;
}) {
  const [formData, setFormData] = useState<Partial<TestCase>>(testCase || {
    title: '',
    description: '',
    steps: [{ step_number: 1, action: '', expected: '' }],
    preconditions: '',
    priority: 'P2',
    tags: [],
  });

  const [isSaving, setIsSaving] = useState(false);

  const handleAddStep = () => {
    const steps = formData.steps || [];
    setFormData({
      ...formData,
      steps: [
        ...steps,
        {
          step_number: steps.length + 1,
          action: '',
          expected: '',
        },
      ],
    });
  };

  const handleRemoveStep = (index: number) => {
    const steps = formData.steps || [];
    setFormData({
      ...formData,
      steps: steps.filter((_, i) => i !== index),
    });
  };

  const handleStepChange = (index: number, field: string, value: string) => {
    const steps = formData.steps || [];
    steps[index] = { ...steps[index], [field]: value };
    setFormData({ ...formData, steps });
  };

  const handleSave = async () => {
    setIsSaving(true);
    try {
      await onSave(formData as TestCase);
      onClose();
    } finally {
      setIsSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
      <div className="bg-slate-800 rounded-lg shadow-lg max-w-2xl w-full max-h-[90vh] overflow-y-auto">
        <div className="sticky top-0 flex items-center justify-between p-6 border-b border-slate-700 bg-slate-800">
          <h2 className="text-xl font-semibold text-slate-100">{testCase ? 'Edit' : 'Create'} Test Case</h2>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-600 text-xl">
            ×
          </button>
        </div>

        <div className="p-6 space-y-4">
          {/* Title */}
          <div>
            <label className="block text-sm font-medium text-slate-600 mb-1">Title *</label>
            <input
              type="text"
              value={formData.title || ''}
              onChange={(e) => setFormData({ ...formData, title: e.target.value })}
              className="w-full px-3 py-2 border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
              placeholder="Test case title"
            />
          </div>

          {/* Description */}
          <div>
            <label className="block text-sm font-medium text-slate-600 mb-1">Description</label>
            <textarea
              value={formData.description || ''}
              onChange={(e) => setFormData({ ...formData, description: e.target.value })}
              className="w-full px-3 py-2 border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
              rows={2}
              placeholder="Detailed description"
            />
          </div>

          {/* Preconditions */}
          <div>
            <label className="block text-sm font-medium text-slate-600 mb-1">Preconditions</label>
            <input
              type="text"
              value={formData.preconditions || ''}
              onChange={(e) => setFormData({ ...formData, preconditions: e.target.value })}
              className="w-full px-3 py-2 border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
              placeholder="Setup requirements"
            />
          </div>

          {/* Priority */}
          <div>
            <label className="block text-sm font-medium text-slate-600 mb-1">Priority</label>
            <select
              value={formData.priority || 'P2'}
              onChange={(e) => setFormData({ ...formData, priority: e.target.value })}
              className="w-full px-3 py-2 border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
            >
              {['P0', 'P1', 'P2', 'P3'].map((p) => (
                <option key={p} value={p}>
                  {p}
                </option>
              ))}
            </select>
          </div>

          {/* Steps */}
          <div>
            <div className="flex items-center justify-between mb-2">
              <label className="block text-sm font-medium text-slate-600">Steps *</label>
              <button
                onClick={handleAddStep}
                className="text-sm px-2 py-1 bg-blue-100 hover:bg-blue-200 text-blue-700 rounded"
              >
                + Add Step
              </button>
            </div>
            <div className="space-y-3">
              {(formData.steps || []).map((step, index) => (
                <div key={index} className="p-3 border border-slate-700 rounded-lg bg-slate-800/50">
                  <div className="flex items-center gap-2 mb-2">
                    <span className="text-sm font-semibold text-slate-400">Step {index + 1}</span>
                    {(formData.steps?.length || 0) > 1 && (
                      <button
                        onClick={() => handleRemoveStep(index)}
                        className="ml-auto text-red-600 hover:text-red-700 text-sm"
                      >
                        Remove
                      </button>
                    )}
                  </div>
                  <input
                    type="text"
                    value={step.action}
                    onChange={(e) => handleStepChange(index, 'action', e.target.value)}
                    placeholder="Action"
                    className="w-full px-2 py-1 border border-slate-300 rounded text-sm mb-2 focus:outline-none focus:ring-2 focus:ring-blue-500"
                  />
                  <input
                    type="text"
                    value={step.expected}
                    onChange={(e) => handleStepChange(index, 'expected', e.target.value)}
                    placeholder="Expected result"
                    className="w-full px-2 py-1 border border-slate-300 rounded text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                  />
                </div>
              ))}
            </div>
          </div>

          {/* Tags */}
          <div>
            <label className="block text-sm font-medium text-slate-600 mb-1">Tags</label>
            <input
              type="text"
              value={(formData.tags || []).join(', ')}
              onChange={(e) => setFormData({ ...formData, tags: e.target.value.split(',').map((t) => t.trim()) })}
              className="w-full px-3 py-2 border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
              placeholder="Comma-separated tags"
            />
          </div>
        </div>

        <div className="sticky bottom-0 flex gap-2 justify-end p-6 border-t border-slate-700 bg-slate-800/50">
          <button
            onClick={onClose}
            className="px-4 py-2 text-slate-600 border border-slate-300 rounded-lg hover:bg-slate-700 transition-colors"
          >
            Cancel
          </button>
          <button
            onClick={handleSave}
            disabled={isSaving}
            className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:bg-slate-400 transition-colors"
          >
            {isSaving ? 'Saving...' : 'Save'}
          </button>
        </div>
      </div>
    </div>
  );
}

export default function TestCaseEditor({ reqId, onClose }: TestCaseEditorProps) {
  const [testCases, setTestCases] = useState<TestCase[]>([]);
  const [selectedTestCase, setSelectedTestCase] = useState<TestCase | null>(null);
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [isLoading, setIsLoading] = useState(true);
  const [filter, setFilter] = useState<string>('all');
  const [isAugmenting, setIsAugmenting] = useState(false);
  const { activities } = useActivityStream({ reqId });

  useEffect(() => {
    fetchTestCases();
  }, [reqId]);

  const fetchTestCases = async () => {
    setIsLoading(true);
    try {
      const response = await fetch(`/api/tests/${reqId}/cases`);
      if (response.ok) {
        const data = await response.json();
        setTestCases(data.items || []);
      }
    } catch (error) {
      console.error('Failed to fetch test cases:', error);
    } finally {
      setIsLoading(false);
    }
  };

  const handleSaveTestCase = async (testCase: Partial<TestCase>) => {
    try {
      const url = testCase.id ? `/api/tests/${reqId}/cases/${testCase.id}` : `/api/tests/${reqId}/cases`;
      const method = testCase.id ? 'PUT' : 'POST';

      const response = await fetch(url, {
        method,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          title: testCase.title,
          description: testCase.description,
          steps: testCase.steps,
          preconditions: testCase.preconditions,
          priority: testCase.priority,
          tags: testCase.tags,
        }),
      });

      if (response.ok) {
        await fetchTestCases();
      }
    } catch (error) {
      console.error('Failed to save test case:', error);
    }
  };

  const handleValidateTestCase = async (caseId: string) => {
    try {
      const response = await fetch(`/api/tests/${reqId}/cases/${caseId}/validate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
      });

      if (response.ok) {
        // Refresh to show updated validation status
        await new Promise((r) => setTimeout(r, 1000));
        fetchTestCases();
      }
    } catch (error) {
      console.error('Failed to validate test case:', error);
    }
  };

  const handleAugmentTestCases = async () => {
    setIsAugmenting(true);
    try {
      const response = await fetch(`/api/tests/${reqId}/cases/augment`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          target_coverage: 0.8,
          generate_count: 5,
        }),
      });

      if (response.ok) {
        // Wait for A11 to process
        await new Promise((r) => setTimeout(r, 2000));
        fetchTestCases();
      }
    } catch (error) {
      console.error('Failed to augment test cases:', error);
    } finally {
      setIsAugmenting(false);
    }
  };

  const filteredCases = testCases.filter((tc) => {
    if (filter === 'all') return true;
    if (filter === 'validated') return tc.validation_status === 'passed';
    if (filter === 'failed') return tc.validation_status === 'failed';
    if (filter === 'augmented') return tc.source === 'a11_generated';
    return true;
  });

  return (
    <div className="h-full flex flex-col bg-slate-800">
      {/* Header */}
      <div className="flex items-center justify-between p-6 border-b border-slate-700">
        <h1 className="text-2xl font-bold text-slate-100">Test Case Editor</h1>
        <div className="flex gap-2">
          <button
            onClick={() => setIsModalOpen(true)}
            className="px-4 py-2 bg-emerald-600 text-white rounded-lg hover:bg-emerald-700 transition-colors"
          >
            + New Test Case
          </button>
          <button
            onClick={handleAugmentTestCases}
            disabled={isAugmenting}
            className="px-4 py-2 bg-purple-600 text-white rounded-lg hover:bg-purple-700 disabled:bg-slate-400 transition-colors"
          >
            {isAugmenting ? 'Augmenting...' : 'A11 Smart Augment'}
          </button>
          {onClose && (
            <button
              onClick={onClose}
              className="px-4 py-2 text-slate-600 border border-slate-300 rounded-lg hover:bg-slate-700"
            >
              Close
            </button>
          )}
        </div>
      </div>

      <div className="flex-1 flex gap-6 overflow-hidden p-6">
        {/* Main Content */}
        <div className="flex-1 flex flex-col min-w-0">
          {/* Filter */}
          <div className="mb-4 flex gap-2">
            {['all', 'validated', 'failed', 'augmented'].map((f) => (
              <button
                key={f}
                onClick={() => setFilter(f)}
                className={`px-3 py-1 text-sm rounded-lg border transition-colors ${
                  filter === f
                    ? 'bg-blue-600 text-white border-blue-600'
                    : 'bg-slate-700 text-slate-600 border-slate-300 hover:bg-slate-600'
                }`}
              >
                {f.charAt(0).toUpperCase() + f.slice(1)}
              </button>
            ))}
          </div>

          {/* Test Cases List */}
          <div className="flex-1 overflow-y-auto space-y-3 pr-2">
            {isLoading ? (
              <div className="text-center text-slate-400 py-8">Loading test cases...</div>
            ) : filteredCases.length === 0 ? (
              <div className="text-center text-slate-400 py-8">No test cases found</div>
            ) : (
              filteredCases.map((tc) => (
                <TestCaseListItem
                  key={tc.id}
                  testCase={tc}
                  onEdit={(t) => {
                    setSelectedTestCase(t);
                    setIsModalOpen(true);
                  }}
                  onValidate={handleValidateTestCase}
                />
              ))
            )}
          </div>
        </div>

        {/* Activity Stream */}
        <div className="w-80 hidden lg:flex flex-col border-l border-slate-700 pl-6">
          <ActivityStream reqId={reqId} />
        </div>
      </div>

      {/* Modal */}
      {isModalOpen && (
        <TestCaseModal
          testCase={selectedTestCase}
          onSave={handleSaveTestCase}
          onClose={() => {
            setIsModalOpen(false);
            setSelectedTestCase(null);
          }}
        />
      )}
    </div>
  );
}
