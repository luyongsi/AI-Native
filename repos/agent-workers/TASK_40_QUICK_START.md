"""
TASK #40 Implementation Complete — Prototype Annotation Hot Update Loop

What Was Built
===============

A complete end-to-end pipeline for prototype annotation and AI-driven UI code generation:

┌─────────────────┐
│ Frontend UI     │  - Draw annotations on prototype image
│ (Canvas)        │  - 3 annotation types: component/interaction/data-binding
└────────┬────────┘
         │ Submit annotations
         ▼
┌─────────────────────────────────────────┐
│ Backend API: POST /api/prototypes/      │
│ - Store in PostgreSQL                   │
│ - Publish NATS event                    │
└────────┬────────────────────────────────┘
         │ "prototype.annotated.{req_id}"
         ▼
┌─────────────────────────────────────────┐
│ A3 Agent (NATS Listener)                │
│ - Parse annotations into UI requirements│
│ - Call LLM to generate React code      │
│ - Publish artifact via activity stream  │
└────────┬────────────────────────────────┘
         │ "agent.A3.artifact" (ui_code_patch)
         ▼
┌─────────────────────────────────────────┐
│ Frontend Real-time Display              │
│ - Activity stream receives code artifact│
│ - CodePreview renders generated code    │
│ - User can copy/download                │
└─────────────────────────────────────────┘


Core Components
===============

1. Frontend PrototypeAnnotator (PrototypeAnnotator.tsx)
   - Canvas with image overlay
   - Click-to-place annotations
   - Draggable/resizable annotation boxes
   - Type selector (component/interaction/data-binding)
   - Properties panel for editing selected annotation
   - Submit button triggers backend API

2. Frontend CodePreview (CodePreview.tsx)
   - Connects to activity stream for selected req_id
   - Listens for "artifact" events with type "ui_code_patch"
   - Displays code with syntax highlighting
   - Copy to clipboard + download buttons
   - Loading indicator while generating

3. Backend API (prototypes.py)
   - POST /api/prototypes/annotate
     * Validate annotation request
     * Store to prototype_annotations table
     * Publish NATS event "prototype.annotated.{req_id}"
     * Return success response
   
   - GET /api/prototypes/annotations/{req_id}
     * Fetch annotation history
     * Return array of annotation versions

4. Database (010_prototype_annotations.sql)
   - prototype_annotations table
   - Columns: id, req_id, image_url, annotations (JSONB), version, created_at
   - Indexes: req_id, created_at
   - Supports multi-version annotation history

5. A3 Agent Enhancement (a3_ui_generator.py)
   - Subscribes to "prototype.annotated.*" on init
   - Handles annotation events asynchronously
   - Parses annotations (component/interaction/data-binding)
   - Generates React code via LLM (DeepSeek)
   - Falls back to template code if LLM fails
   - Publishes artifact "ui_code_patch" via activity stream


Data Structures
===============

Annotation Object:
{
  "id": "ann-1",
  "type": "component" | "interaction" | "data-binding",
  "x": 100,
  "y": 200,
  "width": 300,
  "height": 150,
  "label": "User List Table",
  "properties": {
    // Custom properties per type
  }
}

UI Requirements (parsed from annotations):
{
  "components": [
    {
      "id": "ann-1",
      "name": "User List Table",
      "position": {"x": 100, "y": 200},
      "size": {"width": 300, "height": 150},
      "properties": {...}
    }
  ],
  "interactions": [...],
  "data_bindings": [...]
}

Generated Code Artifact:
{
  "code": "import React from 'react'; export default function...",
  "type": "tsx",
  "components_count": 3,
  "generated_from_annotations": true
}


Event Flow (NATS Subjects)
==========================

Frontend → Backend:
  HTTP POST /api/prototypes/annotate
  
Backend → A3:
  Subject: "prototype.annotated.{req_id}"
  Payload: {req_id, image_url, annotations[], timestamp}

A3 → Frontend (via SSE):
  Subject: "agent.A3.artifact"
  Payload: {req_id, event_type, artifact_type: "ui_code_patch", artifact: {code, type, ...}}


Testing Checklist
=================

Unit Tests:
  [ ] A3._parse_annotations() parses all 3 annotation types
  [ ] A3._generate_from_annotations() generates valid code
  [ ] Backend validation rejects invalid annotation data
  [ ] Database stores and retrieves annotations correctly

Integration Tests:
  [ ] Full flow: Frontend → Backend → A3 → Frontend
  [ ] Multiple annotation versions accumulate in history
  [ ] Activity stream filters events by req_id
  [ ] Code preview updates when artifact is received

Manual Testing:
  [ ] Can draw annotations on prototype image
  [ ] Annotation properties panel edits work
  [ ] Submit button successfully posts to backend
  [ ] Activity stream shows progress ("正在生成中...")
  [ ] Generated code appears in CodePreview
  [ ] Copy/download buttons work
  [ ] Annotation history endpoint returns multiple versions


Known Limitations & Future Work
================================

Current Limitations:
  - Code generation depends on LLM availability (has fallback)
  - Annotations are simple rectangles (no freeform shapes)
  - No visual diff between annotation versions
  - No component preview alongside generated code

Future Enhancements:
  - Freeform annotation drawing (lasso tool)
  - Side-by-side component preview
  - Annotation templates/library
  - Collaborative annotations (multiple users)
  - Auto-generate component hierarchy
  - Integration with design tools (Figma/Sketch export)


Deployment Checklist
====================

Database:
  [ ] Run migration 010_prototype_annotations.sql
  [ ] Verify table created with indexes

Backend:
  [ ] Include prototypes.py router in main.py ✓
  [ ] NATS connection initialized
  [ ] Database pool connected

Frontend:
  [ ] PrototypeAnnotator component available
  [ ] CodePreview component available
  [ ] Activity stream hook working

A3 Agent:
  [ ] A3 init() subscribes to prototype.annotated.*
  [ ] NATS connection active
  [ ] Activity recorder available

Monitoring:
  [ ] NATS events flowing
  [ ] Database queries performing well
  [ ] Activity stream SSE connections stable


Quick Start
===========

1. Start Services:
   cd repos/infra
   docker-compose up -d nats postgres redis

2. Run Migrations:
   cd repos/mc-backend
   python -m alembic upgrade head

3. Start Backend:
   uvicorn main:app --reload

4. Start A3 Agent:
   cd repos/agent-workers
   python worker_launcher.py a3

5. In Frontend:
   - Navigate to prototype view
   - Click PrototypeAnnotator component
   - Upload/display prototype image
   - Click "开始标注" to enter annotation mode
   - Click on image to add annotations
   - Select type from dropdown
   - Edit properties in panel
   - Click "提交标注"
   - Watch CodePreview update with generated code

6. Monitor:
   - Check backend logs: [API] Stored annotations...
   - Check A3 logs: [A3] Received annotation event...
   - Activity stream should show progress events
"""
