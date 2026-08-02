from learning.exercises.dto import ExerciseSpec
from learning.practice.handler_versions import active_handler_version


class ExerciseComposer:
    def __init__(self, *, selection_policy, matching_group_size=4):
        self.selection_policy = selection_policy
        self.matching_group_size = max(2, int(matching_group_size))

    def compose(self, *, learning_items, allowed_types=None):
        specs = []
        recent_types = []
        index = 0
        used_item_ids = set()
        items = tuple(learning_items)

        while index < len(items):
            item = items[index]
            if item.item_id in used_item_ids:
                index += 1
                continue

            remaining_count = len(items) - index
            kind = self.selection_policy.select(
                learning_item=item,
                allowed_types=allowed_types,
                recent_types=tuple(recent_types[-3:]),
                remaining_items_count=remaining_count,
            )

            group = (item,)
            if kind == 'matching':
                group = self._matching_group(items[index:], used_item_ids)
                if len(group) < 2:
                    kind = self.selection_policy.select(
                        learning_item=item,
                        allowed_types=tuple(t for t in (allowed_types or ()) if t != 'matching') or ('multiple_choice', 'translation_ru'),
                        recent_types=tuple(recent_types[-3:]),
                        remaining_items_count=1,
                    )
                    group = (item,)

            for grouped_item in group:
                used_item_ids.add(grouped_item.item_id)

            specs.append(ExerciseSpec(
                kind=kind,
                handler_version=active_handler_version(kind),
                learning_items=tuple(group),
                metadata={
                    'visual_exercise_index': len(specs),
                    'learning_items_count': len(group),
                },
            ))
            recent_types.append(kind)
            index += len(group)

        return tuple(specs)

    def _matching_group(self, remaining_items, used_item_ids):
        group = []
        for item in remaining_items:
            if item.item_id in used_item_ids:
                continue
            if item.item_type not in ('word', 'memory_card'):
                continue
            group.append(item)
            if len(group) >= self.matching_group_size:
                break
        return tuple(group)
