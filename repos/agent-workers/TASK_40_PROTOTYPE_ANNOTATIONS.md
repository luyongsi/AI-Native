"""
TASK #40: Prototype Annotation Interaction - MC Annotation → A3 Hot Update Loop

Implementation Summary
======================

This task implements a complete prototype annotation interaction flow where:
1. Frontend allows marking up prototype images with UI annotations
2. Annotations are submitted to the backend
3. Backend stores annotations and triggers A3 via NATS event
4. A3 generates incremental UI code from annotations
5. Generated code is streamed to frontend via SSE
6. Frontend displays generated code in real-time

Architecture
============

Frontend Components:
  - PrototypeAnnotator.tsx: Canvas-based annotation tool with 3 types (component/interaction/data-binding)
  - CodePreview.tsx: Real-time code display that updates via activity stream

Backend API:
  - POST /api/prototypes/annotate: Accept and store annotations, trigger A3
  - GET /api/prototypes/annotations/{req_id}: Fetch annotation history

Database:
  - prototype_annotations table: Stores annotations with versioning

Event Flow (NATS):
  - Frontend submits annotations
  - Backend publishes "prototype.annotated.{req_id}" event
  - A3 subscribes to "prototype.annotated.*" events
  - A3 generates code and publishes artifact via activity stream

Agent Worker:
  - A3 enhanced to handle annotation events
  - Parses annotations into UI requirements
  - Generates React component code via LLM
  - Publishes code artifact for frontend consumption

Data Flow Example
=================

1. Frontend Annotation:
   {
     "req_id": "uuid-123",
     "image_url": "s3://bucket/prototype.png",
     "annotations": [
       {
         "id": "ann-1",
         "type": "component",
         "label": "Header",
         "x": 0, "y": 0, "width": 1200, "height": 80,
         "properties": {}
       },
       {
         "id": "ann-2",
         "type": "interaction",
         "label": "Click button to submit",
         "x": 1000, "y": 100, "width": 100, "height": 40,
         "properties": {"action": "submit"}
       }
     ]
   }

2. Backend Storage & NATS Event:
   - INSERT into prototype_annotations table
   - PUBLISH to "prototype.annotated.uuid-123"

3. A3 Processing:
   - SUBSCRIBE receives event
   - PARSE annotations → UI requirements
   - CALL LLM with component descriptions
   - GET React .tsx code
   - PUBLISH artifact via activity stream

4. Frontend Reception:
   - Activity stream receives artifact event
   - CodePreview component updates with code
   - User sees generated code in real-time

Acceptance Criteria Checklist
=============================

[x] Frontend annotation UI with drawing on prototype image
[x] Support for 3 annotation types (component/interaction/data-binding)
[x] Annotation submission to backend API
[x] Backend storage in PostgreSQL with versioning
[x] NATS event trigger for A3
[x] A3 annotation event listener
[x] A3 code generation from annotations
[x] Activity stream artifact publishing
[x] Frontend real-time code display
[x] Annotation history retrieval API
[x] Mock/fallback code generation

Files Implemented
=================

Frontend:
  - frontend/src/components/PrototypeAnnotator.tsx
  - frontend/src/components/CodePreview.tsx

Backend:
  - repos/mc-backend/api/prototypes.py
  - repos/mc-backend/db/migrations/010_prototype_annotations.sql

Agent Worker:
  - repos/agent-workers/a3_ui_generator.py (enhanced)
    - Added: handle_annotation_update()
    - Added: _parse_annotations()
    - Added: _generate_from_annotations()
    - Added: _fallback_component_code()
    - Added: init() subscription

Backend Integration:
  - repos/mc-backend/main.py (updated to include prototypes router)

Usage Example
=============

1. Start system:
   docker-compose up  # DB, NATS, backend, A3 worker

2. In frontend UI:
   - Open prototype image
   - Click "开始标注" to enter annotation mode
   - Click on image to create annotations
   - Select annotation type (component/interaction/data-binding)
   - Edit label, position, size in properties panel
   - Click "提交标注"

3. Observe:
   - Backend receives annotation event
   - Activity stream shows "正在生成中..."
   - A3 worker generates code from annotations
   - CodePreview component displays generated React code
   - User can copy or download generated code

4. Query history:
   GET /api/prototypes/annotations/{req_id}
   Returns: list of all annotation versions with timestamps

Testing
=======

Unit Tests:
  - A3._parse_annotations(): Verify annotation parsing
  - A3._generate_from_annotations(): Verify code generation
  - Backend POST /api/prototypes/annotate: Verify storage + event publishing

Integration Tests:
  - End-to-end: Frontend → Backend → A3 → Frontend
  - Annotation persistence: Multiple annotation submissions

Mock Testing:
  - A3 code generation uses fallback when LLM unavailable
  - Frontend handles missing code gracefully

Performance Considerations
===========================

- Annotations stored as JSONB for flexible querying
- Indexed on req_id for fast lookups
- Activity stream filtering by req_id for targeted updates
- Code generation runs asynchronously (no blocking)
- Heartbeats keep SSE connections alive

Future Enhancements
===================

- Batch annotation updates (multiple versions in single flow)
- Visual diff of code changes between annotation versions
- Component preview/preview alongside generated code
- Annotation library/templates for common patterns
- Collaborative annotations (multiple users annotating)
- Annotation-to-Figma/Sketch integration
"""

# Example test scenarios for manual verification

TEST_SCENARIOS = """

Scenario 1: Simple Component Annotation
========================================
1. Frontend submits 3 component annotations (Header, Content, Footer)
2. A3 receives event and parses annotations
3. LLM generates React layout component
4. Frontend displays code with button/input components

Expected: Generated code includes Header/Content/Footer layout

Scenario 2: Annotation with Interaction
========================================
1. Frontend submits component + interaction annotations
2. Interaction label: "Click to load data"
3. A3 generates code with onClick handler
4. Frontend displays code with state management

Expected: Generated code includes React hooks and event handlers

Scenario 3: Data Binding Annotation
===================================
1. Frontend submits data-binding annotation on table
2. Label: "Bind to user list API"
3. A3 generates code with useEffect + fetch
4. Frontend displays code with API integration

Expected: Generated code includes useEffect and data fetching logic

Scenario 4: Annotation History
==============================
1. Frontend submits initial annotations
2. Frontend submits updated annotations (version 2)
3. Call GET /api/prototypes/annotations/{req_id}
4. Response includes both v1 and v2 with timestamps

Expected: Returns array with 2 annotation records, ordered by time DESC
"""
