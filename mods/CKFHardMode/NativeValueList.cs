using System;
using System.Linq;
using System.Reflection;

namespace CKFHardMode
{
    // Generated List<T>.Add checks CLR typeof(T).IsValueType. A native struct
    // represented by an Il2CppSystem.ValueType CLASS fails that check: the
    // wrapper passes the boxed object header as the native struct payload.
    // This bridge explicitly supplies the unboxed payload to runtime_invoke.
    internal sealed class NativeValueList
    {
        private unsafe delegate IntPtr InvokeNative(IntPtr method, IntPtr instance, void** args, ref IntPtr error);
        private Type listType, entryType;
        private PropertyInfo pointer;
        private FieldInfo methodPointer;
        private MethodInfo invokeMethod, unboxMethod, raiseMethod;
        private InvokeNative invoke;
        private Func<IntPtr, IntPtr> unbox;
        private Action<IntPtr> raise;

        internal NativeValueList(Type list, Type entry)
        {
            if (entry.IsValueType || entry.BaseType?.FullName != "Il2CppSystem.ValueType")
                throw new InvalidOperationException("Expected a boxed native value-type proxy: " + entry.FullName);
            listType = list;
            entryType = entry;
            pointer = StunClub.RequireProperty(StunClub.RequireType("Il2CppInterop.Runtime.InteropTypes.Il2CppObjectBase"),
                "Pointer", typeof(IntPtr));
            methodPointer = list.GetFields(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Static)
                .Single(f => f.FieldType == typeof(IntPtr)
                    && f.Name.StartsWith("NativeMethodInfoPtr_Add_", StringComparison.Ordinal));
            var api = StunClub.RequireType("Il2CppInterop.Runtime.IL2CPP");
            unsafe
            {
                invokeMethod = api.GetMethod("il2cpp_runtime_invoke", new[] { typeof(IntPtr), typeof(IntPtr),
                    typeof(void**), typeof(IntPtr).MakeByRefType() })
                    ?? throw new MissingMethodException(api.FullName, "il2cpp_runtime_invoke");
            }
            unboxMethod = api.GetMethod("il2cpp_object_unbox", new[] { typeof(IntPtr) })
                ?? throw new MissingMethodException(api.FullName, "il2cpp_object_unbox");
            raiseMethod = StunClub.RequireType("Il2CppInterop.Runtime.Il2CppException")
                .GetMethod("RaiseExceptionIfNecessary", new[] { typeof(IntPtr) })
                ?? throw new MissingMethodException("Il2CppException.RaiseExceptionIfNecessary");
        }

        internal unsafe void Add(object list, object entry)
        {
            if (list == null || !listType.IsInstanceOfType(list) || entry == null || !entryType.IsInstanceOfType(entry))
                throw new InvalidOperationException("native value list or entry has an unexpected type");
            if (invoke == null)
            {
                var nativeInvoke = (InvokeNative)invokeMethod.CreateDelegate(typeof(InvokeNative));
                var nativeUnbox = (Func<IntPtr, IntPtr>)unboxMethod.CreateDelegate(typeof(Func<IntPtr, IntPtr>));
                var nativeRaise = (Action<IntPtr>)raiseMethod.CreateDelegate(typeof(Action<IntPtr>));
                unbox = nativeUnbox;
                raise = nativeRaise;
                invoke = nativeInvoke;
            }
            var method = (IntPtr)methodPointer.GetValue(null);
            var listAddress = (IntPtr)pointer.GetValue(list);
            var boxedAddress = (IntPtr)pointer.GetValue(entry);
            if (method == IntPtr.Zero || listAddress == IntPtr.Zero || boxedAddress == IntPtr.Zero)
                throw new InvalidOperationException("native value insertion has a null method or object pointer");
            IntPtr payload = unbox(boxedAddress);
            if (payload == IntPtr.Zero) throw new InvalidOperationException("native value unboxing returned null");
            IntPtr error = IntPtr.Zero;
            invoke(method, listAddress, (void**)&payload, ref error);
            // Both wrappers root their native objects through the entire call.
            GC.KeepAlive(entry);
            GC.KeepAlive(list);
            raise(error);
        }
    }
}
