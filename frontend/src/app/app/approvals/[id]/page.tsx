'use client';

import { useState, useEffect, useCallback } from "react";
import { useParams, useRouter } from "next/navigation";
import { api } from "@/lib/api";
import type { Gate0Approval, RejectReason } from "@/lib/types";

export default function ApprovalDetailPage() {
  const params = useParams();
  const router = useRouter();
  const id = params.id as string;
  const [approval, setApproval] = useState<Gate0Approval | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [decision, setDecision] = useState<'pass' | 'reject' | null>(null);
  const [rejectReasons, setRejectReasons] = useState<RejectReason[]>([{ category: 'other', description: '' }]);
  const [revisionGuidance, setRevisionGuidance] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);

  const fetchData = useCallback(async () => {
    try { setLoading(true); setError(null); const res = await api.getApproval(id); setApproval(res); }
    catch (err: any) { setError(err.message || 'Load failed'); }
    finally { setLoading(false); }
  }, [id]);

  useEffect(() => { fetchData(); }, [fetchData]);

  if (loading) {
    return <div className="flex items-center justify-center h-[60vh]"><div className="animate-spin h-8 w-8 border-2 border-slate-300 border-t-slate-600 rounded-full" /></div>;
  }

  if (error || !approval) {
    return (
      <div className="flex flex-col items-center justify-center h-[60vh] gap-3">
        <div className="text-red-500 text-sm">{error || "Not found"}</div>
        <button onClick={() => router.push("/app/approvals")} className="text-blue-600 hover:underline text-xs">Back</button>
      </div>
    );
  }

  const isPending = approval.status === 'pending';
  const statusLabel = approval.status === 'pending' ? 'Pending' : approval.decision === 'pass' ? 'Approved' : approval.decision === 'reject' ? 'Rejected' : 'Decided';
  const gateMeta = approval.gate_meta;

  const addRejectReason = () => setRejectReasons([...rejectReasons, { category: 'other', description: '' }]);
  const updateRejectReason = (idx: number, value: string) => {
    const updated = [...rejectReasons];
    updated[idx] = { ...updated[idx], description: value };
    setRejectReasons(updated);
  };

  const handleSubmit = async () => {
    if (!decision) return;
    try {
      setSubmitting(true); setSubmitError(null);
      await api.decideApproval(id, {
        decision,
        reject_reasons: decision === 'reject' ? rejectReasons.filter(r => r.description.trim()) : [],
        revision_guidance: decision === 'reject' ? revisionGuidance : '',
      });
      router.push("/app/approvals");
    } catch (err: any) {
      setSubmitError(err.message || 'Submit failed');
    } finally { setSubmitting(false); }
  };

  return (
    <div className="max-w-3xl mx-auto p-6">
      <div className="flex items-center justify-between mb-6">
        <div>
          <button onClick={() => router.push("/app/approvals")} className="text-xs text-slate-400 hover:text-slate-400 mb-1">← Back</button>
          <h1 className="text-lg font-semibold text-slate-100">Approval Detail</h1>
        </div>
        <span className={`text-xs px-2.5 py-1 rounded-full font-medium ${
          approval.decision === 'pass' ? 'bg-green-100 text-green-700' :
          approval.decision === 'reject' ? 'bg-red-100 text-red-700' :
          'bg-amber-100 text-amber-700'
        }`}>{statusLabel}</span>
      </div>

      <div className="bg-slate-800 rounded-xl border border-slate-700 p-5 mb-4">
        <div className="grid grid-cols-2 gap-4 text-sm">
          <div><span className="text-xs text-slate-400">Approval ID</span><p className="text-slate-200 font-mono text-xs mt-0.5">{approval.id}</p></div>
          <div><span className="text-xs text-slate-400">Gate</span><p className="mt-0.5"><span className="text-xs px-2 py-0.5 rounded bg-violet-100 text-violet-700">{gateMeta?.label || `Gate ${approval.gate_level}`}</span></p></div>
          <div><span className="text-xs text-slate-400">Requirement</span><p className="text-slate-200 mt-0.5">{approval.req_id}</p></div>
          <div><span className="text-xs text-slate-400">Reviewer</span><p className="text-slate-200 mt-0.5">{approval.reviewer_name || "-"}</p></div>
          <div><span className="text-xs text-slate-400">Cycle</span><p className="text-slate-200 mt-0.5">Cycle {approval.cycle}</p></div>
          <div><span className="text-xs text-slate-400">Created</span><p className="text-slate-200 mt-0.5">{approval.created_at ? new Date(approval.created_at).toLocaleString("zh-CN") : "-"}</p></div>
        </div>
      </div>

      {isPending && (
        <div className="bg-slate-800 rounded-xl border border-slate-700 p-5">
          <h2 className="text-sm font-semibold text-slate-200 mb-4">Decision</h2>
          <div className="flex gap-3 mb-4">
            <button onClick={() => setDecision("pass")}
              className={`flex-1 py-2 rounded-lg text-sm font-medium border-2 transition-all ${
                decision === 'pass' ? 'border-green-500 bg-green-50 text-green-700' : 'border-slate-700 text-slate-400 hover:border-green-300'
              }`}>Pass</button>
            <button onClick={() => setDecision("reject")}
              className={`flex-1 py-2 rounded-lg text-sm font-medium border-2 transition-all ${
                decision === 'reject' ? 'border-red-500 bg-red-50 text-red-700' : 'border-slate-700 text-slate-400 hover:border-red-300'
              }`}>Reject</button>
          </div>

          {decision === 'reject' && (
            <div className="mb-4 space-y-3">
              <div className="flex items-center justify-between">
                <span className="text-xs font-medium text-slate-400">Reject Reasons</span>
                <button onClick={addRejectReason} className="text-xs text-blue-600 hover:text-blue-700">+ Add</button>
              </div>
              {rejectReasons.map((reason, idx) => (
                <input key={idx} value={reason.description} onChange={(e) => updateRejectReason(idx, e.target.value)}
                  placeholder={`Reason #${idx + 1}...`}
                  className="w-full text-sm border border-slate-700 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-red-500/20 focus:border-red-400" />
              ))}
              <textarea value={revisionGuidance} onChange={(e) => setRevisionGuidance(e.target.value)}
                placeholder="Revision guidance (required)..." rows={3}
                className="w-full text-sm border border-slate-700 rounded-lg px-3 py-2 resize-none focus:outline-none focus:ring-2 focus:ring-red-500/20 focus:border-red-400" />
            </div>
          )}

          {submitError && <div className="text-xs text-red-500 bg-red-50 rounded-lg px-3 py-2 mb-4">{submitError}</div>}
          <button onClick={handleSubmit} disabled={!decision || submitting}
            className="w-full py-2 bg-slate-900 text-white text-sm font-medium rounded-lg hover:bg-slate-800 disabled:opacity-50 disabled:cursor-not-allowed transition-colors">
            {submitting ? "Submitting..." : "Submit Decision"}
          </button>
        </div>
      )}

      {!isPending && approval.decision && (
        <div className={`rounded-xl border p-5 ${
          approval.decision === 'pass' ? 'bg-green-50 border-green-200' : 'bg-red-50 border-red-200'
        }`}>
          <div className="flex items-center gap-2 mb-2">
            <div className={`w-8 h-8 rounded-full flex items-center justify-center ${
              approval.decision === 'pass' ? 'bg-green-200 text-green-700' : 'bg-red-200 text-red-700'
            }`}>{approval.decision === "pass" ? "✓" : "✗"}</div>
            <span className="text-sm font-semibold">{approval.decision === 'pass' ? 'Approved' : 'Rejected'}</span>
          </div>
          <p className="text-xs text-slate-400">
            Reviewer: {approval.reviewer_name || "-"} | Reviewed: {approval.reviewed_at ? new Date(approval.reviewed_at).toLocaleString("zh-CN") : "-"}
          </p>
        </div>
      )}
    </div>
  );
}
