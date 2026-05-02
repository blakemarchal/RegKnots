# Crew tier (D6.49) — co-work test plan

**Status**: Backend live on prod behind `CREW_TIER_ENABLED=true` + `CREW_TIER_INTERNAL_ONLY=true`. UI deferred to next session. This doc walks through the API-level verification.

**Run this with**: Blake + Karynn together (both already auto-internal). Plan to spend ~30-45 min.

**Goal**: Validate every workspace flow before turning the feature on for real users — create, invite, rotate, transfer, abuse cases, audit trail.

---

## 0. Pre-flight (5 min)

### 0.1 Confirm both accounts are internal

```sql
-- Run via the prod DB shell
SELECT email, is_internal, full_name
FROM users
WHERE email IN ('blakemarchal@gmail.com', 'kdmarchal@gmail.com');
```

Expected: both rows show `is_internal=true`.

If either is `false`, flip via:
```sql
UPDATE users SET is_internal = TRUE WHERE email = '<email>';
```

### 0.2 Confirm feature flag is enabled

```bash
ssh root@68.183.130.3 "grep CREW_TIER /opt/RegKnots/.env"
```

Expected:
```
CREW_TIER_ENABLED=true
CREW_TIER_INTERNAL_ONLY=true
```

### 0.3 Sign up the supporting test personas

In private/incognito browser windows, sign up:
- `blakemarchal+matea@gmail.com` (mate on Captain A's watch)
- `blakemarchal+chiefeng@gmail.com` (rotating chief engineer)

Both will be auto-flagged `is_internal=true` via migration 0020.

### 0.4 Get JWT tokens for everyone

For each persona, log in and capture the access token. Save them to env vars:

```bash
TOKEN_BLAKE=$(curl -s -X POST https://regknots.com/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"blakemarchal@gmail.com","password":"…"}' \
  | jq -r '.access_token')

TOKEN_KARYNN=$(...)
TOKEN_MATE=$(...)
TOKEN_ENG=$(...)
```

Also capture each user's `id`:
```bash
USER_BLAKE=$(curl -s https://regknots.com/api/auth/me \
  -H "Authorization: Bearer $TOKEN_BLAKE" | jq -r '.user_id')
USER_KARYNN=$(...)
USER_MATE=$(...)
USER_ENG=$(...)
```

---

## 1. Workspace creation (Captain A, 3 min)

### 1.1 Create the workspace

```bash
WS_ID=$(curl -s -X POST https://regknots.com/api/workspaces \
  -H "Authorization: Bearer $TOKEN_BLAKE" \
  -H 'Content-Type: application/json' \
  -d '{"name":"MV Karynn-Q (D6.49 Test)"}' \
  | jq -r '.id')

echo "Workspace ID: $WS_ID"
```

**Expected response shape**:
```json
{
  "id": "uuid",
  "name": "MV Karynn-Q (D6.49 Test)",
  "owner_user_id": "<USER_BLAKE>",
  "status": "trialing",
  "seat_cap": 10,
  "member_count": 1,
  "my_role": "owner",
  "created_at": "..."
}
```

### 1.2 Confirm the workspace appears in the owner's list

```bash
curl -s https://regknots.com/api/workspaces \
  -H "Authorization: Bearer $TOKEN_BLAKE" | jq
```

**Expected**: array containing your workspace with `my_role: "owner"`.

### 1.3 Confirm Karynn does NOT see it yet

```bash
curl -s https://regknots.com/api/workspaces \
  -H "Authorization: Bearer $TOKEN_KARYNN" | jq
```

**Expected**: empty array `[]`.

---

## 2. Invitations (5 min)

### 2.1 Invite Karynn as Admin (rotation captain)

```bash
curl -s -X POST https://regknots.com/api/workspaces/$WS_ID/members \
  -H "Authorization: Bearer $TOKEN_BLAKE" \
  -H 'Content-Type: application/json' \
  -d '{"email":"kdmarchal@gmail.com","role":"admin"}' | jq
```

**Expected**: 201 with `role: "admin"`, Karynn's user_id, joined_at timestamp.

### 2.2 Invite the mate as Member

```bash
curl -s -X POST https://regknots.com/api/workspaces/$WS_ID/members \
  -H "Authorization: Bearer $TOKEN_BLAKE" \
  -H 'Content-Type: application/json' \
  -d '{"email":"blakemarchal+matea@gmail.com","role":"member"}' | jq
```

**Expected**: 201 with `role: "member"`.

### 2.3 Verify Karynn now sees the workspace

```bash
curl -s https://regknots.com/api/workspaces \
  -H "Authorization: Bearer $TOKEN_KARYNN" | jq
```

**Expected**: array with the workspace, `my_role: "admin"`.

### 2.4 View full member list

```bash
curl -s https://regknots.com/api/workspaces/$WS_ID \
  -H "Authorization: Bearer $TOKEN_BLAKE" | jq '.members'
```

**Expected**: 3 members (owner Blake, admin Karynn, member Mate). Order: owner first, then admin, then member.

### 2.5 Negative case — invite a non-existent email

```bash
curl -s -o /dev/null -w '%{http_code}\n' \
  -X POST https://regknots.com/api/workspaces/$WS_ID/members \
  -H "Authorization: Bearer $TOKEN_BLAKE" \
  -H 'Content-Type: application/json' \
  -d '{"email":"doesnotexist@example.com","role":"member"}'
```

**Expected**: `404` ("No RegKnots account exists for that email").

### 2.6 Negative case — duplicate invitation

```bash
curl -s -o /dev/null -w '%{http_code}\n' \
  -X POST https://regknots.com/api/workspaces/$WS_ID/members \
  -H "Authorization: Bearer $TOKEN_BLAKE" \
  -H 'Content-Type: application/json' \
  -d '{"email":"kdmarchal@gmail.com","role":"member"}'
```

**Expected**: `409` ("User is already a member of this workspace").

---

## 3. Role enforcement (5 min)

### 3.1 Karynn (admin) can manage members

```bash
# Karynn invites the chief engineer
curl -s -X POST https://regknots.com/api/workspaces/$WS_ID/members \
  -H "Authorization: Bearer $TOKEN_KARYNN" \
  -H 'Content-Type: application/json' \
  -d '{"email":"blakemarchal+chiefeng@gmail.com","role":"member"}' | jq
```

**Expected**: 201 — admin can invite. Confirms parity for rotation: both captains can manage crew.

### 3.2 Karynn (admin) CANNOT change roles

```bash
curl -s -o /dev/null -w '%{http_code}\n' \
  -X PATCH https://regknots.com/api/workspaces/$WS_ID/members/$USER_MATE \
  -H "Authorization: Bearer $TOKEN_KARYNN" \
  -H 'Content-Type: application/json' \
  -d '{"role":"admin"}'
```

**Expected**: `403` ("Requires one of: owner").

### 3.3 Owner promotes mate to admin

```bash
curl -s -X PATCH https://regknots.com/api/workspaces/$WS_ID/members/$USER_MATE \
  -H "Authorization: Bearer $TOKEN_BLAKE" \
  -H 'Content-Type: application/json' \
  -d '{"role":"admin"}' | jq '.role'
```

**Expected**: `"admin"`.

### 3.4 Karynn (admin) CANNOT remove another admin

```bash
curl -s -o /dev/null -w '%{http_code}\n' \
  -X DELETE https://regknots.com/api/workspaces/$WS_ID/members/$USER_MATE \
  -H "Authorization: Bearer $TOKEN_KARYNN"
```

**Expected**: `403` ("Admin cannot remove another admin. Owner must do that").

### 3.5 Mate (member after demotion) can self-remove

First demote mate back to member:
```bash
curl -s -X PATCH https://regknots.com/api/workspaces/$WS_ID/members/$USER_MATE \
  -H "Authorization: Bearer $TOKEN_BLAKE" \
  -H 'Content-Type: application/json' \
  -d '{"role":"member"}' | jq '.role'
```

Then mate self-removes:
```bash
curl -s -o /dev/null -w '%{http_code}\n' \
  -X DELETE https://regknots.com/api/workspaces/$WS_ID/members/$USER_MATE \
  -H "Authorization: Bearer $TOKEN_MATE"
```

**Expected**: `204`. Mate then re-invites for next test:
```bash
curl -X POST https://regknots.com/api/workspaces/$WS_ID/members \
  -H "Authorization: Bearer $TOKEN_BLAKE" \
  -H 'Content-Type: application/json' \
  -d '{"email":"blakemarchal+matea@gmail.com","role":"member"}'
```

---

## 4. Owner removal protection (1 min)

### 4.1 Try to remove the Owner — blocked

```bash
curl -s -o /dev/null -w '%{http_code}\n' \
  -X DELETE https://regknots.com/api/workspaces/$WS_ID/members/$USER_BLAKE \
  -H "Authorization: Bearer $TOKEN_BLAKE"
```

**Expected**: `400` ("Owner cannot be removed. Transfer ownership first…").

This protects the rotation case — even the Owner can't accidentally orphan a workspace.

---

## 5. Ownership transfer (the captain-retiring case, 5 min)

### 5.1 Transfer Owner from Blake to Karynn

```bash
curl -s -X POST https://regknots.com/api/workspaces/$WS_ID/transfer \
  -H "Authorization: Bearer $TOKEN_BLAKE" \
  -H 'Content-Type: application/json' \
  -d "{\"new_owner_user_id\":\"$USER_KARYNN\"}" | jq
```

**Expected response**:
```json
{
  "id": "...",
  "owner_user_id": "<USER_KARYNN>",
  "status": "card_pending",
  "card_pending_started_at": "<now>",
  "my_role": "admin"   ← caller (Blake) is now demoted
}
```

### 5.2 Karynn now sees herself as Owner

```bash
curl -s https://regknots.com/api/workspaces/$WS_ID \
  -H "Authorization: Bearer $TOKEN_KARYNN" | jq '{my_role, status, card_pending_started_at}'
```

**Expected**: `my_role: "owner"`, `status: "card_pending"`, timestamp populated.

### 5.3 Blake (now admin) cannot transfer ownership

```bash
curl -s -o /dev/null -w '%{http_code}\n' \
  -X POST https://regknots.com/api/workspaces/$WS_ID/transfer \
  -H "Authorization: Bearer $TOKEN_BLAKE" \
  -H 'Content-Type: application/json' \
  -d "{\"new_owner_user_id\":\"$USER_MATE\"}"
```

**Expected**: `403`.

### 5.4 Try to transfer to a Member (non-Admin) — blocked

```bash
# Karynn tries to transfer to mate who is just a member
curl -s -o /dev/null -w '%{http_code}\n' \
  -X POST https://regknots.com/api/workspaces/$WS_ID/transfer \
  -H "Authorization: Bearer $TOKEN_KARYNN" \
  -H 'Content-Type: application/json' \
  -d "{\"new_owner_user_id\":\"$USER_MATE\"}"
```

**Expected**: `400` ("New owner must be an Admin first. Promote them, then retry the transfer.").

### 5.5 Verify the audit trail

```bash
ssh root@68.183.130.3 "docker exec regknots-postgres psql -U regknots -d regknots -P pager=off -c \\
  \"SELECT created_at, event_type, details FROM workspace_billing_events \\
    WHERE workspace_id = '$WS_ID' ORDER BY created_at DESC LIMIT 5;\""
```

**Expected**:
- `owner_transferred` event with `details` JSON containing `from_user_id`, `to_user_id`, `status_after: "card_pending"`, `grace_days: 30`.
- `created` event from earlier in the test.

---

## 6. Seat cap (3 min)

### 6.1 Inspect current seat usage

```bash
curl -s https://regknots.com/api/workspaces/$WS_ID \
  -H "Authorization: Bearer $TOKEN_KARYNN" | jq '{member_count, seat_cap}'
```

**Expected**: `member_count: 3`, `seat_cap: 10`.

### 6.2 Hit the cap by inviting plus-addressed personas

```bash
for i in 1 2 3 4 5 6 7; do
  curl -s -o /dev/null -w "+test$i: %{http_code}\n" \
    -X POST https://regknots.com/api/workspaces/$WS_ID/members \
    -H "Authorization: Bearer $TOKEN_KARYNN" \
    -H 'Content-Type: application/json' \
    -d "{\"email\":\"blakemarchal+test$i@gmail.com\",\"role\":\"member\"}"
done
```

**Expected**: First few succeed if those accounts exist (they won't unless you've signed them up), or 404 each. The point is — when you DO have 10 members, the 11th will return `400` with "Seat cap reached".

You can also verify at the DB level:
```sql
SELECT COUNT(*) FROM workspace_members WHERE workspace_id = '$WS_ID';
```

---

## 7. Sign-off checklist

Run through this together at the end:

- [ ] Workspace creation returned 201 with status='trialing'
- [ ] Both captains see the workspace in their `/workspaces` lists
- [ ] Mate cannot manage members; admin/owner can
- [ ] Admin cannot transfer ownership or change roles
- [ ] Owner can promote/demote between admin and member
- [ ] Owner cannot be removed without transfer
- [ ] Transfer demotes old Owner to admin and elevates new Owner
- [ ] Status flips to `card_pending` on transfer with timestamp
- [ ] `workspace_billing_events` has the audit row
- [ ] Seat cap blocks 11th member
- [ ] Duplicate invite returns 409
- [ ] Non-existent email invite returns 404
- [ ] Workspace list scope: each user sees only workspaces they belong to

If all 12 boxes pass: **greenlight Phase 2 of D6.49** (frontend UI + workspace-scoped chat + Stripe wiring).

If anything fails: capture the curl response, the workspace_id, and the persona that hit it. Open a follow-up note on the [Phase 2 review endpoint](../sprint-audits/web-fallback-d6-48-phase-1.md) approach to surface it.

---

## Cleanup (when done)

```sql
-- Optional: nuke the test workspace + audit
DELETE FROM workspaces WHERE id = '<WS_ID>';
-- workspace_members and workspace_billing_events cascade.
```

Or leave it as a permanent reference workspace for ongoing rotation tests.

---

## What's NOT covered by this test (deferred to next session)

- Frontend UI for workspaces (currently API-only)
- Workspace-scoped chat (conversations are still user-scoped — your STRETCH DUCK 07 chats still belong to you, not to a workspace yet)
- Stripe customer creation + card management
- 30-day expiry → `archived` automation (no cron yet)
- Workspace-scoped credentials + dossier + Coming Up widget

Those are Phase 2 of the crew tier (separate sprint). Today's verification is the foundation: the auth + roles + transfer flow has to be bulletproof before we layer billing on top.
