/**
 * coding_exercise_type_toggle.js
 *
 * Shows/hides fieldsets and the CodingAnswer inline on the
 * CodingExercise admin change-form based on the selected question_type.
 */
(function () {
    'use strict';

    var CODE_TYPES   = ['write_code'];
    var ANSWER_TYPES = ['multiple_choice', 'true_false'];
    var SHORT_TYPES  = ['short_answer', 'fill_blank'];

    function updateVisibility() {
        var select = document.getElementById('id_question_type');
        if (!select) { return; }
        var qt = select.value;

        // Fieldset: code exercise fields
        document.querySelectorAll('.code-exercise-fields').forEach(function (el) {
            el.style.display = CODE_TYPES.indexOf(qt) !== -1 ? '' : 'none';
        });

        // Fieldset: short / fill-blank answer field
        document.querySelectorAll('.short-answer-fields').forEach(function (el) {
            el.style.display = SHORT_TYPES.indexOf(qt) !== -1 ? '' : 'none';
        });

        // Inline: CodingAnswer rows
        var inlineGroup = document.getElementById('codinganswer_set-group');
        if (inlineGroup) {
            inlineGroup.style.display = ANSWER_TYPES.indexOf(qt) !== -1 ? '' : 'none';
        }
    }

    document.addEventListener('DOMContentLoaded', function () {
        var select = document.getElementById('id_question_type');
        if (select) {
            select.addEventListener('change', updateVisibility);
            updateVisibility();
        }
    });
})();
