#!/usr/bin/env python
# coding=utf-8
import gdb, json, datetime
from string import punctuation

def ptrtohex(val):
    return hex((int(val) + (1 << 64)) % (1 << 64))

def numtoptr(num):
    return gdb.Value(num).cast(gdb.lookup_type('uint64_t').pointer())

def vtoint(value):
    return value.cast(gdb.lookup_type('uint64_t'))

def get_addr_content(addr):
    return gdb.Value(int(addr)).cast(gdb.lookup_type('uint64_t').pointer()).dereference();

def get_ptr_obj(addr, struct_name):
    return gdb.Value(int(addr)).cast(gdb.lookup_type('struct '+struct_name).pointer());

def get_symbol_addr(symbol):
    return gdb.lookup_global_symbol(symbol).value().address 

cpu0_offset = gdb.lookup_global_symbol('__per_cpu_offset').value()[0]
current_task_offset = get_symbol_addr('current_task')

def cprint(*info):

    if info[-1] == 1:
        pos = -2
    else:
        pos = -1

    for i in info[0:pos]:
        if info[pos] == 'red': 
            print('\033[31;2m'+str(i)+'\033[0m', end='')
            continue

        if info[pos] == 'green': 
            print('\033[32;15m'+str(i)+'\033[0m', end='')
            continue

        if info[pos] == 'yellow': 
            print('\033[33;10m'+str(i)+'\033[0m', end='')
            continue

        if info[pos] == 'blue': 
            print('\033[34;10m'+str(i)+'\033[0m', end='')
            continue

        if info[pos] == 'deep_green': 
            print('\033[36;10m'+str(i)+'\033[0m', end='')
            continue

        if info[pos] == 'white': 
            print('\033[37;10m'+str(i)+'\033[0m', end='')
            continue

    if info[-1] == 1:
        pass
    else:
        print()


def get_current_task():
    current_task_ptr = vtoint(cpu0_offset)+vtoint(current_task_offset)
    current_task = get_addr_content(current_task_ptr)
    current = get_ptr_obj(current_task, 'task_struct')
    name = current['comm'].string()
    pid = vtoint(current['pid'])
    return (name, pid)

def get_task_struct(pid):

    RADIX_TREE_INTERNAL_NODE = 2
    RADIX_TREE_MAP_MASK = 0x3f
    init_pid_ns_addr = get_symbol_addr('init_pid_ns') 
    init_pid_ns = get_ptr_obj(init_pid_ns_addr, 'pid_namespace')
    idr_base = init_pid_ns['idr']['idr_base']
    index = pid - idr_base
    xa_head = init_pid_ns['idr']['idr_rt']['xa_head']
    node = xa_head

    while True:
        parent = vtoint(node) & (~RADIX_TREE_INTERNAL_NODE)
        shift = get_ptr_obj(parent, 'xa_node')['shift']
        offset = (index >> int(shift)) & RADIX_TREE_MAP_MASK
        node = get_ptr_obj(parent, 'xa_node')['slots'][offset]
        if(shift == 0):
            break

    first = get_ptr_obj(node, 'pid')['tasks'][0]
    task_struct = vtoint(first) - 0x500

    cprint("task_struct: ", ptrtohex(task_struct), 'green')
    comm = get_ptr_obj(task_struct, 'task_struct')['comm']
    cprint("comm:", comm, 'green')


def get_kernel_base():
    kernel_base = get_symbol_addr('__startup_64')
    kernel_base = vtoint(kernel_base) & 0xffffffffffff0000
    cprint("kernel_base: ", ptrtohex(kernel_base), 'green')

def get_struct_offset(struct, field, user=1):
    exist = 0
    fields = gdb.lookup_type('struct '+struct).fields()
    for f in fields:
        if f.name == field:
            offset = f.bitpos//8
            if user == 1:
                cprint(field+" in "+ struct + "'s offset: ", hex(offset), 'green')
            exist = 1
            break
    if exist == 0:
        cprint("The field doesn't exist.", 'red')
        return 
    return offset



def recursion(fields, level):
    for f in fields:
        if f.name == None:
            cprint("    "*level, str(f.type)[0:-4], 'green')
            level += 1
            recursion(f.type.fields(), level)
            level -= 1
            cprint("    "*level, "};" , 'green')
        else:
            cprint("    "*level, f.type, 'green', 1)
            cprint(' ', f.name, ";", 'white') # '\n'

def get_struct_content(struct):
    fields = gdb.lookup_type('struct '+struct).fields()
    struct_name = gdb.lookup_type('struct '+struct).strip_typedefs()
    cprint(struct_name, " { ",'green')
    
    recursion(fields, 1)
    cprint("}; ",'green')
    return

#----------------------------------------------------------------------
        
def get_next_cache(cache, list_offset):
    next = cache['list']['next']
    next_cache = get_ptr_obj(vtoint(next)-list_offset, 'kmem_cache')
    return next_cache

def get_freelist(freelist, offset):
    while True:
        if freelist != 0:
            cprint("    ->", ptrtohex(freelist), 'deep_green')
        else:
            cprint("    ->", ptrtohex(freelist), ' (freelist)', 'deep_green')
            break
        freelist = get_addr_content(freelist + offset)

def get_partial_freelist(next_page, offset, page_num, page_type, color):

    cprint(page_type, " partial page", page_num, ": ", ptrtohex(next_page), color)

    if next_page != 0:
        partial_page = get_ptr_obj(next_page, 'page')
        partial_free = vtoint(partial_page['freelist']) 
        get_freelist(partial_free, offset)

def get_cpu_partial_page(partial, offset):
    page_num = 0
    next_page = get_ptr_obj(partial, 'page') # page0
    while True:
        get_partial_freelist(next_page, offset, page_num, 'cache_cpu', 'red') # print freelist
        next = vtoint(next_page['next'])
        next_page = get_ptr_obj(next, 'page')
        if next_page == 0:
            break
        page_num += 1

def get_node_partial_page(node_page_partial_next, node_page_partial_prev, offset):
    page_num = 0
    node_partial_page = node_page_partial_next - 0x8
    next_page = get_ptr_obj(node_partial_page, 'page') # page0
    next_lru = node_page_partial_next
    while True:
        get_partial_freelist(next_page, offset, page_num, 'cache_node', 'yellow') # print freelist
        if(next_lru == node_page_partial_prev):
            break
        next_lru = get_ptr_obj(next_lru, 'list_head')
        next_lru = vtoint(next_lru['next'])
        next = next_lru - 0x8
        next_page = get_ptr_obj(next, 'page')
        page_num += 1

def get_kmem_cache(kmem_cache_name):

    list_offset = get_struct_offset('kmem_cache', 'list', 0)
    slab_caches = get_symbol_addr('slab_caches')
    start = get_ptr_obj(vtoint(slab_caches)-list_offset, 'kmem_cache')
    cprint("start: ", start, 'red')
    next = get_next_cache(start, list_offset)

    while True:
        #------kmem_cache
        name = next['name'].string()
        min_partial = next['min_partial']
        cpu_partial = next['cpu_partial']  # next -> kmem_cache
        oo = vtoint(next['oo']) & 0xffffffff
        objects_count = (oo & ((1 << 16) -1)) 
        pages_count = (2 ** (oo >> 16))
        offset = vtoint(next['offset'])

        #-----kmem_cache_cpu
        cpu_slab_offset = vtoint(next['cpu_slab'])
        cache_cpu = get_ptr_obj(cpu0_offset + cpu_slab_offset, 'kmem_cache_cpu')
        free = vtoint(cache_cpu['freelist']) # kmem_cache_cpu freelist 
        page = ptrtohex(cache_cpu['page'])
        partial = vtoint(cache_cpu['partial']) # kmem_cache_cpu partial 

        #-----kmem_cache_node
        node = vtoint(next['node'])   
        cache_node_0 = get_addr_content(node) # get first node
        cache_node = get_ptr_obj(cache_node_0, 'kmem_cache_node') # change to struct kmem_cache_node *
        
        if name == kmem_cache_name: 
            #-------------print kmem_cache information
            cprint("cpu #0 > ", ptrtohex(cpu0_offset), " | ", cache_cpu, 'red')
            cprint('<'+kmem_cache_name+'>:', 'red')
            cprint('kmem_cache    : ', ptrtohex(next), 'green')
            cprint('oo            : ', oo, 'green')
            cprint('objects_count : ', objects_count, 'green')
            cprint('pages_count   : ', pages_count, 'green')
            cprint('offset        : ', offset, 'green')
            cprint('min_partial   : ', min_partial, 'green')
            cprint('cpu_partial   : ', cpu_partial, 'green')
            #print('random: ', random)
            #cprint('page        : ', page, 'green') # kmem_cache_cpu page
            
            #-------------kmem_cache_cpu freelist
            cprint("cache_cpu freelist: ", 'deep_green')
            get_freelist(free, offset)

            #-------------kmem_cache_cpu partial
            if partial == 0:
                cprint("cache_cpu partial page", " -> ", ptrtohex(partial), 'red')
            else:
                get_cpu_partial_page(partial, offset)

            #-------------kmem_cache_node partial
            cprint('first cache_node addr : ', ptrtohex(cache_node), 'yellow') 
            cprint("cache_node['partial']['next']: ", cache_node['partial']['next'], 'yellow')
            node_page_partial_next = vtoint(cache_node['partial']['next'])
            node_page_partial_prev = vtoint(cache_node['partial']['prev'])
            if node_page_partial_next == node_page_partial_prev:
                cprint("cache_node partial page", " -> ", '0x0' , 'yellow')
            else:
                get_node_partial_page(node_page_partial_next, node_page_partial_prev, offset)

            #-------------kmem_cache_node full
            node_page_full_next = vtoint(cache_node['full']['next'])
            node_page_full_prev = vtoint(cache_node['full']['prev'])
            if node_page_full_next == node_page_full_prev:
                cprint("cache_node full page", " -> ", '0x0 ', 'yellow')
            else:
                cprint("cache_node full page", " -> ", node_page_partial_next , 'red')

            break

        next = get_next_cache(next, list_offset)
        if start == next:
            break


BP_flag = 1
dill_name = ''
ZERO_SIZE_PTR = 0x10

class kmem_cache_alloc_BP(gdb.Breakpoint):
    def stop(self):
        global BP_flag
        s = gdb.selected_frame().read_var('s')
        name, pid = get_current_task()
        if name != dill_name or BP_flag == 0:
            return False
        cache = s['name'].string()
        cprint('kmem_cache_alloc:', cache, ', name: ', name, ', pid: ', pid, 'yellow')

        return False

class kmalloc_slab_FBP(gdb.FinishBreakpoint):
    def stop(self):
        global BP_flag
        name, pid = get_current_task()
        if name != dill_name or BP_flag == 0:
            return False
        ret = self.return_value
        if ret == ZERO_SIZE_PTR:
            cprint('kmalloc has been called with argument size=0: ',', name: ', name, ', pid: ', pid,  'green')
            return False
        cache = ret['name'].string()
        cprint('kmalloc_slab: ', cache, 'green', 1)

        return False

class kmalloc_slab_BP(gdb.Breakpoint):
    def stop(self):
        kmalloc_slab_FBP(internal=True)
        return False

class kmalloc_FBP(gdb.FinishBreakpoint):
    def stop(self):
        global BP_flag
        name, pid = get_current_task()
        if name != dill_name or BP_flag == 0:
            return False
        ret = self.return_value
        cprint(' -> __kmalloc: ', ret ,', name: ', name, ', pid: ', pid,  'green')
        return False

class kmalloc_BP(gdb.Breakpoint):
    def stop(self):
        kmalloc_FBP(internal=True)
        return False

class kfree_FBP(gdb.FinishBreakpoint):
    def stop(self):
        name, pid = get_current_task()
        rdi = gdb.selected_frame().read_register('rdi')
        if rdi == 0 or rdi == ZERO_SIZE_PTR or rdi == 0x40000000:
            return False
        try:
            cache = rdi.cast(gdb.lookup_type('struct kmem_cache').pointer()).dereference()
            cache = cache['name'].string()
            cprint(' -> kfree_FBP: ', cache,', name: ', name, ', pid: ', pid,  'deep_green')
        except:
            print('kfree_FBP error')
        
        return False

class kfree_BP(gdb.Breakpoint):
    def stop(self):
        global BP_flag
        name, pid = get_current_task()
        if name != dill_name or BP_flag == 0:
            return False
        x = gdb.selected_frame().read_var('x')
        cprint('kfree object at address: ', x, 'deep_green', 1)
        kfree_FBP(internal=True)
        return False

class kmem_cache_free_BP(gdb.Breakpoint):
    def stop(self):
        name,pid = get_current_task()
        if name != dill_name or BP_flag == 0:
            return False
        try:
            s = gdb.selected_frame().read_var('s')
            x = gdb.selected_frame().read_var('x')
            cache = s['name'].string()
            cprint('kmem_cache_free: ', cache, ', name: ', name, ', pid: ', pid, 'deep_green')
        except:
            print("kmem_cache_free_BP error!")
        return False

class dill(gdb.Command):
    def __init__ (self):
        super (dill, self).__init__ ("dill", gdb.COMMAND_USER)
    def invoke(self, arg, from_tty):
        global BP_flag, dill_name
        if not arg:
            print('Command error!')
        else:
            args = arg.split()
            if len(args) == 1:
                if args[0] == 'run':
                    kmem_cache_alloc_BP('kmem_cache_alloc', internal=True)
                    kmalloc_slab_BP('kmalloc_slab', internal=True)
                    kmalloc_BP('__kmalloc', internal=True)
                    kfree_BP('kfree', internal=True)
                    #kmem_cache_free_BP('kmem_cache_free',internal=True)
                elif args[0] == 'on':
                    BP_flag = 1
                elif args[0] == 'off':
                    BP_flag = 0
                else:
                    dill_name = args[0]
                    cprint("To trace the process: ", dill_name, 'green')
            else:
                print('args are too much!')


class kstruct(gdb.Command):
    def __init__ (self):
        super (kstruct, self).__init__ ("kstruct", gdb.COMMAND_USER)
    def invoke(self, arg, from_tty):
        if not arg:
            print('Command error!')
        else:
            args = arg.split()
            if len(args) == 1:
                get_struct_content(args[0])
            elif len(args) == 2:
                get_struct_offset(args[0], args[1])
            else:
                print('args are too much!')

class ktask(gdb.Command):
    def __init__ (self):
        super (ktask, self).__init__ ("ktask", gdb.COMMAND_USER)
    def invoke(self, arg, from_tty):
        if not arg:
            print('Command error!')
        else:
            args = arg.split()
            if len(args) == 1:
                get_task_struct(int(args[0]))
            else:
                print('args are too much!')

class kbase(gdb.Command):
    def __init__ (self):
        super (kbase, self).__init__ ("kbase", gdb.COMMAND_USER)
    def invoke(self, arg, from_tty):
        if not arg:
            get_kernel_base()
        else:
            print('args are too much!')

class kcache(gdb.Command):
    def __init__ (self):
        super (kcache, self).__init__ ("kcache", gdb.COMMAND_USER)
    def invoke(self, arg, from_tty):
        if not arg:
            print('Command error!')
        else:
            args = arg.split()
            if len(args) == 1:
                get_kmem_cache(str(args[0]))
            else:
                print('args are too much!')


kstruct()
ktask()
kbase()
kcache()
dill()
