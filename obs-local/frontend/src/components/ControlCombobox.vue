<script setup lang="ts">
import {
  Combobox,
  ComboboxButton,
  ComboboxInput,
  ComboboxOption,
  ComboboxOptions,
  TransitionRoot,
} from "@headlessui/vue";
import { computed, ref, watch } from "vue";

const props = withDefaults(
  defineProps<{
    modelValue: string;
    options: readonly string[];
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

const query = ref(props.modelValue);

watch(
  () => props.modelValue,
  (value) => {
    query.value = value;
  },
);

const filteredOptions = computed(() => {
  const normalizedQuery = query.value.trim().toLowerCase();
  if (!normalizedQuery) {
    return props.options;
  }
  return props.options.filter((item) => item.toLowerCase().includes(normalizedQuery));
});

const menuStyle = computed(() => ({
  minWidth: props.minWidth ?? undefined,
}));

function handleInput(event: Event): void {
  const nextValue = (event.target as HTMLInputElement).value;
  query.value = nextValue;
  emit("update:modelValue", nextValue);
}

function handleSelect(value: string): void {
  query.value = value;
  emit("update:modelValue", value);
}
</script>

<template>
  <Combobox :model-value="modelValue" @update:model-value="handleSelect">
    <div class="control-combobox" :data-align="align">
      <div class="control-combobox__field">
        <ComboboxInput
          class="control-combobox__input"
          :aria-label="ariaLabel"
          :display-value="(value: unknown) => (typeof value === 'string' ? value : '')"
          :placeholder="placeholder"
          @change="handleInput"
        />
        <ComboboxButton class="control-combobox__button" :aria-label="ariaLabel">
          <span class="control-combobox__chevron" aria-hidden="true" />
        </ComboboxButton>
      </div>

      <TransitionRoot
        enter="control-combobox-enter-active"
        enter-from="control-combobox-enter-from"
        enter-to="control-combobox-enter-to"
        leave="control-combobox-leave-active"
        leave-from="control-combobox-leave-from"
        leave-to="control-combobox-leave-to"
      >
        <ComboboxOptions v-if="filteredOptions.length" class="control-combobox__menu" :style="menuStyle">
          <ComboboxOption
            v-for="option in filteredOptions"
            :key="option"
            v-slot="{ active, selected }"
            as="template"
            :value="option"
          >
            <li
              class="control-combobox__option"
              :class="{
                'control-combobox__option--active': active,
                'control-combobox__option--selected': selected,
              }"
            >
              <span>{{ option }}</span>
              <span v-if="selected" class="control-combobox__check" aria-hidden="true" />
            </li>
          </ComboboxOption>
        </ComboboxOptions>
      </TransitionRoot>
    </div>
  </Combobox>
</template>

<style scoped>
.control-combobox {
  position: relative;
}

.control-combobox__field {
  position: relative;
  display: flex;
  align-items: center;
  min-height: 2.4rem;
  min-width: 7rem;
  border: 1px solid color-mix(in srgb, var(--color-border-strong) 70%, rgba(122, 230, 242, 0.2) 30%);
  border-radius: 999px;
  background:
    linear-gradient(135deg, rgba(76, 201, 215, 0.08), rgba(96, 165, 250, 0.06)),
    linear-gradient(180deg, rgba(17, 27, 47, 0.96), rgba(10, 17, 31, 0.98));
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.05),
    0 10px 22px rgba(2, 8, 23, 0.16);
  transition:
    border-color 140ms ease,
    box-shadow 140ms ease;
}

.control-combobox__field:focus-within,
.control-combobox__field:hover {
  border-color: color-mix(in srgb, var(--color-brand) 56%, var(--color-border-strong) 44%);
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.07),
    0 12px 28px rgba(2, 8, 23, 0.2);
}

.control-combobox__input {
  width: 100%;
  min-width: 0;
  height: 2.4rem;
  padding: 0 2.95rem 0 0.95rem;
  border: 0;
  background: transparent;
  color: var(--color-text-primary);
  outline: none;
}

.control-combobox__input::placeholder {
  color: var(--color-text-tertiary);
}

.control-combobox__button {
  position: absolute;
  top: 0;
  right: 0;
  bottom: 0;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 2.55rem;
  border: 0;
  border-radius: 0 999px 999px 0;
  background: linear-gradient(90deg, rgba(255, 255, 255, 0), rgba(122, 230, 242, 0.06));
  cursor: pointer;
}

.control-combobox__button:focus-visible {
  outline: none;
}

.control-combobox__field:hover .control-combobox__button,
.control-combobox__field:focus-within .control-combobox__button {
  background: linear-gradient(90deg, rgba(255, 255, 255, 0.01), rgba(122, 230, 242, 0.1));
}

.control-combobox__chevron {
  width: 0.5rem;
  height: 0.5rem;
  border-right: 2px solid color-mix(in srgb, var(--color-brand-strong) 72%, white 28%);
  border-bottom: 2px solid color-mix(in srgb, var(--color-brand-strong) 72%, white 28%);
  transform: rotate(45deg) translateY(-0.08rem);
}

.control-combobox__menu {
  position: absolute;
  top: calc(100% + 0.55rem);
  left: 0;
  z-index: 18;
  min-width: max(100%, 12rem);
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

.control-combobox[data-align="right"] .control-combobox__menu {
  left: auto;
  right: 0;
}

.control-combobox__option {
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

.control-combobox__option--active {
  background: rgba(255, 255, 255, 0.04);
  color: var(--color-text-primary);
}

.control-combobox__option--selected {
  background:
    linear-gradient(135deg, rgba(76, 201, 215, 0.18), rgba(96, 165, 250, 0.12)),
    linear-gradient(180deg, rgba(24, 40, 71, 0.98), rgba(14, 24, 44, 0.98));
  color: #effbff;
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.06),
    0 0 0 1px rgba(122, 230, 242, 0.12);
}

.control-combobox__check {
  width: 0.72rem;
  height: 0.38rem;
  border-left: 2px solid var(--color-brand-strong);
  border-bottom: 2px solid var(--color-brand-strong);
  transform: rotate(-45deg);
}

.control-combobox-enter-active,
.control-combobox-leave-active {
  transition:
    opacity 140ms ease,
    transform 140ms ease;
}

.control-combobox-enter-from,
.control-combobox-leave-to {
  opacity: 0;
  transform: translateY(-4px);
}

.control-combobox-enter-to,
.control-combobox-leave-from {
  opacity: 1;
  transform: translateY(0);
}
</style>
