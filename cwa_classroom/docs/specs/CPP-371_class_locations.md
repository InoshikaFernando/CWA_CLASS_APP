# CPP-371: Locations for the classes

## Problem

An institute may run classes at more than one venue — separate branches or
rooms — and some classes are delivered online. Before this change the app had
no concept of a class venue: the only address in the system was the institute's
own registered address (`School.address` / the structured company address on
the settings page), and a class had a day and time but no place.

We need:

1. A place to record as many **locations** as an institute needs, each with a
   name and an **optional** address.
2. A way to mark a location (and a class) as **online**, so a class can be
   pure online, in-person only, or a mix of both.
3. A **location** field on a class, set alongside the class day and time.

Locations belong to the **institute** (`School`) — they are not the institute's
own address.

## Data model

### New model — `classroom.Location`

`classroom/models.py`. School-scoped venue.

| Field        | Type                          | Notes                                   |
| ------------ | ----------------------------- | --------------------------------------- |
| `school`     | FK → `School` (CASCADE)       | `related_name='locations'`.             |
| `name`       | `CharField(200)`              | Required — the picklist label.          |
| `address`    | `TextField(blank=True)`       | **Optional** street address.            |
| `is_online`  | `BooleanField(default=False)` | Marks a virtual / online venue.         |
| `is_active`  | `BooleanField(default=True)`  | Inactive locations are hidden from pickers. |
| `created_at` / `updated_at` | timestamps     |                                         |

`Meta.ordering = ['name']`.

### `classroom.ClassRoom` — two new fields

- `location` — FK → `Location`, `null=True, blank=True`, **`on_delete=SET_NULL`**
  so deleting a location clears it from any class without deleting the class.
  `related_name='classrooms'`. Set alongside day/start/end time.
- `is_online` — `BooleanField(default=False)`. Marks the class as delivered
  online.

### Delivery mode (derived)

`ClassRoom.delivery_mode` (property) + `get_delivery_mode_display()` resolve the
two fields into a single label — no separate mode field is stored:

| `location` | `is_online` | `delivery_mode` | Display                        |
| ---------- | ----------- | --------------- | ------------------------------ |
| set        | `False`     | `in_person`     | In-person                      |
| —          | `True`      | `online`        | Online                         |
| set        | `True`      | `hybrid`        | Hybrid (in-person + online)    |
| —          | `False`     | `''`            | (unset)                        |

Migration: `classroom/migrations/0114_classroom_is_online_location_classroom_location.py`.

## Managing locations

### View — `LocationManageView`

`classroom/views_admin.py`. `RoleRequiredMixin`, roles ADMIN /
INSTITUTE_OWNER / HEAD_OF_INSTITUTE. Modeled on `TermManageView`. A single page
handling list + `create` / `edit` / `delete` POST actions, each scoped to the
requesting user's school via `_get_user_school_or_404`. All mutations write an
`audit` `log_event` (`location_created` / `location_edited` / `location_deleted`).

- **create**: name required; address + online optional.
- **edit**: 404 if the location is not in the caller's school (cross-tenant
  guard); an unchecked `is_online` box clears the flag.
- **delete**: `SET_NULL` detaches the location from any classes (they survive);
  the success message reports how many classes had their location cleared.

Route: `admin-dashboard/schools/<school_id>/locations/` →
`admin_school_locations`.

Template: `templates/admin_dashboard/school_locations.html` — add form +
inline Alpine edit rows, matching the Terms page.

### Discovery

`templates/admin_dashboard/school_detail.html` gains a **Locations** quick-stat
card (count + link to the manage page) in the top stats row;
`SchoolDetailView` passes `locations` to the context.

## Class create / edit

All three class create/edit surfaces gain a **Location** picker (options are the
active locations of the class's institute, "No location" is allowed) and an
**Online class** checkbox, placed after the Day & Time block:

- `CreateClassView` (`teacher/create_class.html`)
- `EditClassView` (`teacher/edit_class.html`) — pre-selects the current values
- `HoDCreateClassView` (`hod/create_class.html`)

Server-side, a submitted location is only accepted if it belongs to the class's
institute (`Location.objects.filter(id=..., school=department.school)`); an
unknown/foreign id resolves to `None` rather than erroring — no silent
cross-tenant assignment.

The class detail page (`teacher/class_detail.html`) shows a 📍 location badge
and an "Online" badge next to the day/time badges.

## Tests

- **Unit** — `classroom/tests/test_cpp371_locations.py`: model defaults +
  `delivery_mode` matrix + `SET_NULL` behaviour; `LocationManageView`
  create/edit/delete + name-required + cross-tenant 404; class create/edit
  wiring location + online, clearing them, and rejecting a foreign location.
- **UI** — `ui_tests/test_locations.py`: add-location form, create persists
  with address + online flag, the school-detail Locations link, and delete.
