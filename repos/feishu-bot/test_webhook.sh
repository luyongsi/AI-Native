#!/bin/bash
# test_webhook.sh — 模拟飞书向 localhost:8400 发消息

BOT_URL="http://localhost:8400/api/v1/feishu/webhook"

echo "========================================"
echo " Test 1: URL Verification (POST)"
echo "========================================"
curl -s -X POST "$BOT_URL" \
  -H "Content-Type: application/json" \
  -d '{"type":"url_verification","challenge":"test_challenge_abc123"}' \
  | python3 -m json.tool
echo ""

echo "========================================"
echo " Test 2: URL Verification (GET)"
echo "========================================"
curl -s -X GET "$BOT_URL?challenge=get_challenge_xyz789" \
  | python3 -m json.tool
echo ""

echo "========================================"
echo " Test 3: IM Message - batch export"
echo "========================================"
curl -s -X POST "$BOT_URL" \
  -H "Content-Type: application/json" \
  -H "X-Lark-Request-Timestamp: $(date +%s)" \
  -H "X-Lark-Request-Nonce: test-nonce-001" \
  -H "X-Lark-Signature: skip-dev" \
  -d '{"type":"im.message.receive_v1","event":{"message":{"chat_id":"oc_test_001","content":"{\"text\":\"订单详情页加个批量导出功能\"}"},"sender":{"sender_id":"user_test_001"}}}' \
  | python3 -m json.tool
echo ""

echo "========================================"
echo " Test 4: IM Message - color change"
echo "========================================"
curl -s -X POST "$BOT_URL" \
  -H "Content-Type: application/json" \
  -H "X-Lark-Request-Timestamp: $(date +%s)" \
  -H "X-Lark-Request-Nonce: test-nonce-002" \
  -H "X-Lark-Signature: skip-dev" \
  -d '{"type":"im.message.receive_v1","event":{"message":{"chat_id":"oc_test_002","content":"{\"text\":\"导航栏背景颜色改成深蓝色\"}"},"sender":{"sender_id":"user_test_002"}}}' \
  | python3 -m json.tool
echo ""

echo "========================================"
echo " Test 5: IM Message - permission"
echo "========================================"
curl -s -X POST "$BOT_URL" \
  -H "Content-Type: application/json" \
  -H "X-Lark-Request-Timestamp: $(date +%s)" \
  -H "X-Lark-Request-Nonce: test-nonce-003" \
  -H "X-Lark-Signature: skip-dev" \
  -d '{"type":"im.message.receive_v1","event":{"message":{"chat_id":"oc_test_003","content":"{\"text\":\"管理员需要审批普通用户的退款申请权限\"}"},"sender":{"sender_id":"user_test_003"}}}' \
  | python3 -m json.tool
echo ""

echo "========================================"
echo " All tests completed."
echo "========================================"
