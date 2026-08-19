const root = document.querySelector<HTMLElement>('#app');

if (!root) {
  throw new Error('APP_ROOT_MISSING');
}

root.textContent = 'Ozon FBO Supply Optimizer';
