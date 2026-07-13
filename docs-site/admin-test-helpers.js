export class TestElement {
  constructor(name = 'div', ownerDocument = null) {
    this.name = name;
    this.ownerDocument = ownerDocument;
    this.parentNode = null;
    this.children = [];
    this.attributes = new Map();
    this.listeners = new Map();
    this.dataset = {};
    this.className = '';
    this.textContent = '';
    this.value = '';
    this.checked = false;
    this.disabled = false;
    this.hidden = false;
    this.open = false;
    this.focused = false;
    this.connected = true;
  }

  setConnected(value) {
    this.connected = value;
    for (const child of this.children) {
      if (child instanceof TestElement) child.setConnected(value);
    }
  }

  append(...children) {
    for (const child of children) {
      if (child instanceof TestElement) {
        child.parentNode = this;
        child.setConnected(this.connected);
      }
      this.children.push(child);
    }
  }

  replaceChildren(...children) {
    for (const child of this.children) {
      if (child instanceof TestElement) {
        child.parentNode = null;
        child.setConnected(false);
      }
    }
    this.children = [];
    this.append(...children);
  }

  addEventListener(type, listener) {
    const listeners = this.listeners.get(type) || [];
    listeners.push(listener);
    this.listeners.set(type, listeners);
  }

  async dispatchEvent(eventValue) {
    const event = typeof eventValue === 'string' ? { type: eventValue } : eventValue;
    event.target ||= this;
    event.currentTarget = this;
    event.defaultPrevented ||= false;
    event.preventDefault ||= () => { event.defaultPrevented = true; };
    for (const listener of this.listeners.get(event.type) || []) await listener.call(this, event);
    return !event.defaultPrevented;
  }

  setAttribute(name, value) {
    this.attributes.set(name, String(value));
    if (name === 'id') this.ownerDocument?.elements.set(String(value), this);
  }

  getAttribute(name) { return this.attributes.get(name) ?? null; }

  removeAttribute(name) { this.attributes.delete(name); }

  focus() {
    if (!this.isConnected) return;
    if (this.ownerDocument) {
      if (this.ownerDocument.activeElement) this.ownerDocument.activeElement.focused = false;
      this.ownerDocument.activeElement = this;
    }
    this.focused = true;
  }

  showModal() { this.open = true; }

  close(returnValue = '') {
    this.open = false;
    this.returnValue = returnValue;
    return this.dispatchEvent({ type: 'close' });
  }

  click() { return this.dispatchEvent({ type: 'click' }); }

  remove() {
    if (!this.parentNode) return;
    this.parentNode.children = this.parentNode.children.filter((child) => child !== this);
    this.parentNode = null;
    this.setConnected(false);
  }

  querySelectorAll(selector) {
    const matches = [];
    const match = selector === 'input:checked'
      ? (node) => node.name === 'input' && node.checked
      : selector.startsWith('.')
        ? (node) => node.className.split(/\s+/).includes(selector.slice(1))
        : (node) => node.name === selector;
    const visit = (node) => {
      for (const child of node.children) {
        if (!(child instanceof TestElement)) continue;
        if (match(child)) matches.push(child);
        visit(child);
      }
    };
    visit(this);
    return matches;
  }

  get childElementCount() {
    return this.children.filter((child) => child instanceof TestElement).length;
  }

  get isConnected() { return this.connected; }
}

export function createDocument(ids = []) {
  const document = {
    activeElement: null,
    elements: new Map(),
    createElement(name) { return new TestElement(name, document); },
    createTextNode(value) { return String(value); },
    getElementById(id) { return document.elements.get(id) || null; },
  };
  document.body = document.createElement('body');
  for (const id of ids) {
    const node = document.createElement('div');
    node.setAttribute('id', id);
  }
  return document;
}

export function textOf(node) {
  if (typeof node === 'string') return node;
  return (node?.textContent || '') + (node?.children || []).map(textOf).join('');
}

export function jsonResponse(value, { ok = true, status = ok ? 200 : 500 } = {}) {
  return { ok, status, async json() { return value; } };
}
