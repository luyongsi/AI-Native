/**
 * Context Builder API client — fetches task context from the Context Builder service.
 *
 * Stub implementation: returns a mock context package.
 * Real implementation will use the native `fetch()` API:
 *
 *   const res = await fetch(`http://localhost:8000/api/context/${taskId}`);
 *   if (!res.ok) throw new Error(`Context Builder returned ${res.status}`);
 *   return await res.json();
 */

/**
 * Fetch context for a given task ID from the Context Builder API.
 *
 * @param {string} taskId - The unique task identifier
 * @returns {Promise<{ taskId: string, domain: string, api_paths: number, db_tables: number, spec_version: string, requirements_count: number, mock: boolean }>}
 */
export async function fetchContext(taskId) {
  const apiUrl = `http://localhost:8000/api/context/${taskId}`;

  console.log(`[ContextFetcher] [STUB] Would call: GET ${apiUrl}`);

  // ------------------------------------------------------------------
  // Mock context package — mirrors what the real Context Builder returns
  // ------------------------------------------------------------------
  const mockContext = {
    task_id: taskId,
    domain: 'order-management',
    spec_version: '0.2.0',
    api_paths: 6,
    db_tables: 4,
    requirements_count: 3,
    openapi_spec: {
      info: { title: 'order-management', version: '1.0.0' },
      paths: {
        '/orders': { get: {}, post: {} },
        '/orders/{id}': { get: {}, put: {}, delete: {} },
        '/orders/export': { get: {} },
      },
    },
    erd: {
      tables: [
        { name: 'orders', columns: 8 },
        { name: 'order_items', columns: 5 },
        { name: 'customers', columns: 7 },
        { name: 'shipments', columns: 6 },
      ],
    },
    requirements: [
      { id: 'REQ-001', title: 'List orders with pagination', priority: 'high' },
      { id: 'REQ-002', title: 'Export orders to CSV', priority: 'medium' },
      { id: 'REQ-003', title: 'Filter orders by status', priority: 'high' },
    ],
    mock: true,
  };

  return mockContext;
}
