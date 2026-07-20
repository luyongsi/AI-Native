"use client";

import { useRouter } from "next/navigation";
import ConversationView from "@/components/dialogue/ConversationView";

export default function NewRequirementPage() {
  const router = useRouter();

  const handleComplete = (reqId: string) => {
    router.push(`/app/requirements/${reqId}`);
  };

  const handleCancel = () => {
    router.back();
  };

  return (
    <div className="max-w-4xl mx-auto h-[calc(100vh-10rem)] p-6">
      <ConversationView
        initialTitle=""
        onComplete={handleComplete}
        onCancel={handleCancel}
      />
    </div>
  );
}
