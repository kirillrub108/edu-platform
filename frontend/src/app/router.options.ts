import type { RouterConfig } from '@nuxt/schema'

// Disable Nuxt's default scroll-to-top on navigation.
// Scroll restoration is handled entirely by the scroll-restoration plugin.
export default <RouterConfig>{
  scrollBehavior: () => false,
}
