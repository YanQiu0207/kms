<script setup lang="ts">
import {
  Listbox,
  ListboxButton,
  ListboxOption,
  ListboxOptions,
  TransitionRoot,
} from "@headlessui/vue";
import { computed } from "vue";

type SelectValue = string | number;

export interface ControlSelectOption {
  label: string;
  value: SelectValue;
}

const props = withDefaults(
  defineProps<{
    modelValue: string;
    options: readonly ControlSelectOption[];
    placeholder?: string;
    ariaLabel?: string;
    align?: "left" | "right";
    minWidth?: string;
  }>(),
  {
    placeholder: "",
    ariaLabel: undefined,
    align: "left",
    minWidth: undefined,
  },
);

const emit = defineEmits<{
  "update:modelValue": [value: string];
}>();

const selectedOption = computed(() => props.options.find((item) => String(item.value) === props.modelValue) ?? null);
const displayLabel = computed(() => selectedOption.value?.label ?? props.placeholder);
const menuStyle = computed(() => ({
  minWidth: props.minWidth ?? undefined,
}));

function handleUpdate(value: SelectValue): void {
  emit("update:modelValue", String(value));
}
</script>

<template>
  <Listbox :model-value="modelValue" @update:model-value="handleUpdate">
    <div class="control-select" :data-align="align">
      <ListboxButton class="control-select__trigger" :aria-label="ariaLabel">
        <span class="control-select__label">{{ displayLabel }}</span>
        <span class="control-select__chevron" aria-hidden="true" />
      </ListboxButton>

      <TransitionRoot
        enter="control-select-enter-active"
        enter-from="control-select-enter-from"
        enter-to="control-select-enter-to"
        leave="control-select-leave-active"
        leave-from="control-select-leave-from"
        leave-to="control-select-leave-to"
      >
        <ListboxOptions class="control-select__menu" :style="menuStyle">
          <ListboxOption
            v-for="option in options"
            :key="String(option.value)"
            v-slot="{ active, selected }"
            as="template"
            :value="String(option.value)"
          >
            <li
              class="control-select__option"
              :class="{
                'control-select__option--active': active,
                'control-select__option--selected': selected,
              }"
            >
              <span>{{ option.label }}</span>
              <span v-if="selected" class="control-select__check" aria-hidden="true" />
            </li>
          </ListboxOption>
        </ListboxOptions>
      </TransitionRoot>
    </div>
  </Listbox>
</template>

<style scoped>
.control-select {
  position: relative;
}

.control-select__trigger {
  display: inline-flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.8rem;
  min-height: 2.4rem;
  min-width: 7rem;
  padding: 0 0.95rem;
  border: 1px solid color-mix(in srgb, var(--color-border-strong) 70%, rgba(122, 230, 242, 0.2) 30%);
  border-radius: 999px;
  background:
    linear-gradient(135deg, rgba(76, 201, 215, 0.08), rgba(96, 165, 250, 0.06)),
    linear-gradient(180deg, rgba(17, 27, 47, 0.96), rgba(10, 17, 31, 0.98));
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.05),
    0 10px 22px rgba(2, 8, 23, 0.16);
  color: var(--color-text-primary);
  cursor: pointer;
  transition:
    border-color 140ms ease,
    box-shadow 140ms ease,
    transform 140ms ease;
}

.control-select__trigger:hover,
.control-select__trigger[data-headlessui-state~="open"] {
  border-color: color-mix(in srgb, var(--color-brand) 56%, var(--color-border-strong) 44%);
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.07),
    0 12px 28px rgba(2, 8, 23, 0.2);
}

.control-select__trigger:focus-visible {
  outline: none;
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.07),
    0 0 0 3px rgba(76, 201, 215, 0.16),
    0 12px 28px rgba(2, 8, 23, 0.2);
}

.control-select__label {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.control-select__chevron {
  width: 0.5rem;
  height: 0.5rem;
  border-right: 2px solid color-mix(in srgb, var(--color-brand-strong) 72%, white 28%);
  border-bottom: 2px solid color-mix(in srgb, var(--color-brand-strong) 72%, white 28%);
  transform: rotate(45deg) translateY(-0.08rem);
  transition: transform 140ms ease;
}

.control-select__trigger[data-headlessui-state~="open"] .control-select__chevron,
.control-select[data-open="true"] .control-select__chevron {
  transform: rotate(225deg) translateY(0.04rem);
}

.control-select__menu {
  position: absolute;
  top: calc(100% + 0.55rem);
  left: 0;
  z-index: 18;
  min-width: max(100%, 10rem);
  display: grid;
  gap: 0.22rem;
  margin: 0;
  padding: 0.35rem;
  list-style: none;
  border: 1px solid color-mix(in srgb, var(--color-border-strong) 66%, rgba(122, 230, 242, 0.24) 34%);
  border-radius: 1rem;
  background:
    linear-gradient(180deg, rgba(17, 27, 47, 0.98), rgba(9, 16, 29, 0.99)),
    var(--color-surface-raised);
  box-shadow: 0 20px 44px rgba(2, 8, 23, 0.34);
  backdrop-filter: blur(14px);
}

.control-select[data-align="right"] .control-select__menu {
  left: auto;
  right: 0;
}

.control-select__option {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.9rem;
  min-height: 2.35rem;
  padding: 0 0.82rem;
  border-radius: 0.8rem;
  color: var(--color-text-secondary);
  transition:
    background 140ms ease,
    color 140ms ease;
}

.control-select__option--active {
  background: rgba(255, 255, 255, 0.04);
  color: var(--color-text-primary);
}

.control-select__option--selected {
  background:
    linear-gradient(135deg, rgba(76, 201, 215, 0.18), rgba(96, 165, 250, 0.12)),
    linear-gradient(180deg, rgba(24, 40, 71, 0.98), rgba(14, 24, 44, 0.98));
  color: #effbff;
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.06),
    0 0 0 1px rgba(122, 230, 242, 0.12);
}

.control-select__check {
  width: 0.72rem;
  height: 0.38rem;
  border-left: 2px solid var(--color-brand-strong);
  border-bottom: 2px solid var(--color-brand-strong);
  transform: rotate(-45deg);
}

.control-select-enter-active,
.control-select-leave-active {
  transition:
    opacity 140ms ease,
    transform 140ms ease;
}

.control-select-enter-from,
.control-select-leave-to {
  opacity: 0;
  transform: translateY(-4px);
}

.control-select-enter-to,
.control-select-leave-from {
  opacity: 1;
  transform: translateY(0);
}
</style>
