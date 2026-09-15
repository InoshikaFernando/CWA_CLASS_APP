"""Pre-written messages for the Messaging Centre compose page.

Everyone sending a promotion writes the same four emails, badly, at eleven at
night. These are those four, written once, in the voice the rest of the app
uses, with the facts a parent needs actually present: what the offer is, what
happens when it ends, what it costs afterwards, and one link to act on.

**They are starting points, not forms.** Picking one fills the subject and body
and then gets out of the way — every word stays editable, and "Write my own"
starts from a blank page exactly as before. Nothing here is ever sent as-is
without somebody reading it, because the placeholders below make that
impossible.

Placeholders
------------
Two kinds, and the distinction is the whole safety story:

``{{school_name}}`` and friends are **filled in automatically** from what the
compose page already knows. They never reach a recipient.

``[[CODE]]``, ``[[PRICE]]``, ``[[LINK]]``, ``[[DATE]]`` are **left for the
sender**, deliberately in a shape that is impossible to miss and easy to search
for. The compose page refuses to send while any of them remain, because the
failure they prevent is the one that actually happens: two hundred families
receiving an email that tells them to enter the code ``[[CODE]]``. A friendly
grey hint box would not have stopped that; a disabled Send button does.

Kept in Python rather than the HTML so the copy can be tested, reviewed in a
diff, and reused by anything else that needs it later — and so a typo in a
price or a promise is caught by a test rather than by a parent.
"""

#: The marker the compose page scans for, and refuses to send with.
#: Deliberately not ``{{...}}``: that shape is already Django's, and a stray one
#: reaching a template renderer would silently vanish rather than be caught.
SENDER_PLACEHOLDER_PATTERN = r'\[\[[A-Z_]+\]\]'


MESSAGE_TEMPLATES = [
    {
        'key': 'free_trial_invite',
        'name': 'Free trial invitation',
        'description': 'Offer the two-week free code to families who are not subscribed.',
        'subject': 'Two weeks free on {{school_name}} — no card needed',
        'body_html': (
            '<p>Hi there,</p>'
            '<p>We have opened up <strong>two weeks of free access</strong> to the '
            '{{school_name}} learning hub for your child. Homework, practice '
            'questions and progress tracking — all of it, for a fortnight.</p>'
            '<p><strong>No card details are needed.</strong> Nothing is charged '
            'now, nothing is charged when the two weeks end, and there is no '
            'subscription to cancel.</p>'
            '<p>To start, sign in and enter this code when asked:</p>'
            '<p style="font-size:18px;"><strong>[[CODE]]</strong></p>'
            '<p><a href="[[LINK]]">Start the free two weeks</a></p>'
            '<p>A couple of things worth knowing up front, so nothing is a '
            'surprise:</p>'
            '<ul>'
            '<li>The free version covers the questions the app marks itself. The '
            'AI-marked written questions are part of the paid plan.</li>'
            '<li>When the two weeks are up, access pauses and we will show you '
            'the option to continue at [[PRICE]] a month. Nothing happens '
            'automatically.</li>'
            '</ul>'
            '<p>Any questions, just reply to this email.</p>'
        ),
    },
    {
        'key': 'trial_ending_soon',
        'name': 'Free trial ending soon',
        'description': 'Three-day warning, before access pauses.',
        'subject': 'Your {{school_name}} free access ends on [[DATE]]',
        'body_html': (
            '<p>Hi there,</p>'
            '<p>Your child\'s free access to the {{school_name}} learning hub '
            'ends on <strong>[[DATE]]</strong>. We wanted to give you fair '
            'warning rather than let it stop without notice.</p>'
            '<p>Their work, progress and history all stay exactly where they '
            'are — nothing is deleted, and picking up again later loses '
            'nothing.</p>'
            '<p>To carry straight on, you can subscribe for [[PRICE]] a month. '
            'That also adds the AI-marked written questions, which the free '
            'version leaves out.</p>'
            '<p><a href="[[LINK]]">Continue after [[DATE]]</a></p>'
            '<p>If now is not the right time, you do not need to do anything at '
            'all. Nothing will be charged.</p>'
        ),
    },
    {
        'key': 'trial_ended',
        'name': 'Free trial has ended',
        'description': 'After access pauses — how to pick up where they left off.',
        'subject': 'Your {{school_name}} free access has ended',
        'body_html': (
            '<p>Hi there,</p>'
            '<p>The free two weeks on the {{school_name}} learning hub have '
            'finished, so your child\'s account is paused for now.</p>'
            '<p>Everything they did is still there. Subscribing picks up exactly '
            'where they left off — same account, same progress, same classes — '
            'and adds the AI-marked written questions that the free version '
            'left out.</p>'
            '<p><a href="[[LINK]]">Continue for [[PRICE]] a month</a></p>'
            '<p>If you would rather not continue, there is nothing to cancel and '
            'nothing to pay.</p>'
        ),
    },
    {
        'key': 'payment_reminder',
        'name': 'Payment reminder',
        'description': 'For families whose subscription has lapsed or was never started.',
        'subject': 'Action needed to keep your {{school_name}} access',
        'body_html': (
            '<p>Hi there,</p>'
            '<p>Your child\'s {{school_name}} learning account is ready to go, '
            'but it needs a subscription before they can get back in.</p>'
            '<p>It is [[PRICE]] a month, and it covers everything: homework, '
            'practice, progress reports and the AI-marked written questions.</p>'
            '<p><a href="[[LINK]]">Set up the subscription</a></p>'
            '<p>If you were given a discount code, enter it on that page and the '
            'price will update before anything is charged.</p>'
            '<p>If you think this is a mistake, or your child should be covered '
            'by the school, reply to this email and we will sort it out.</p>'
        ),
    },
]


def templates_for(school=None):
    """The templates, with the automatic placeholders already filled in.

    Only ``{{school_name}}`` today. It is substituted here rather than in the
    browser so that a school with an apostrophe or an ampersand in its name is
    escaped once, by Django, instead of being pasted into innerHTML by hand.
    """
    from django.utils.html import escape

    name = escape(school.name) if school is not None else 'our learning hub'
    out = []
    for template in MESSAGE_TEMPLATES:
        out.append({
            **template,
            'subject': template['subject'].replace('{{school_name}}', name),
            'body_html': template['body_html'].replace('{{school_name}}', name),
        })
    return out
