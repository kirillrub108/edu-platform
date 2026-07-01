<script setup lang="ts">
const doc = legalDoc('contacts')
</script>

<template>
  <LegalPage :doc="doc">
    <p>
      Услуги сервиса Edllm оказывает {{ LEGAL_ENTITY.fullName }}. Ниже приведены
      полные реквизиты и контактные данные.
    </p>

    <h2>Контакты</h2>
    <dl>
      <dt>Сайт</dt>
      <dd>
        <a :href="LEGAL_CONTACTS.site" target="_blank" rel="noopener noreferrer">{{ LEGAL_CONTACTS.siteLabel }}</a>
      </dd>
      <dt>E-mail поддержки (основной канал связи)</dt>
      <dd>
        <a :href="`mailto:${LEGAL_CONTACTS.supportEmail}`">{{ LEGAL_CONTACTS.supportEmail }}</a>
      </dd>
      <dt>Телефон</dt>
      <dd>
        <a :href="`tel:${LEGAL_CONTACTS.phoneHref}`">{{ LEGAL_CONTACTS.phone }}</a>
      </dd>
    </dl>

    <h2>Реквизиты индивидуального предпринимателя</h2>
    <dl>
      <dt>Полное наименование</dt>
      <dd>{{ LEGAL_ENTITY.fullName }}</dd>
      <dt>ИНН</dt>
      <dd>{{ LEGAL_ENTITY.inn }}</dd>
      <dt>ОГРНИП</dt>
      <dd>{{ LEGAL_ENTITY.ogrnip }}</dd>
      <dt>Дата регистрации ИП</dt>
      <dd>{{ LEGAL_ENTITY.registeredAt }}</dd>
      <dt>Регистрирующий (налоговый) орган</dt>
      <dd>{{ LEGAL_ENTITY.registrar }}</dd>
      <dt>Основной вид деятельности (ОКВЭД)</dt>
      <dd>{{ LEGAL_ENTITY.primaryOkved.code }} — {{ LEGAL_ENTITY.primaryOkved.title }}</dd>
      <dt>Дополнительные ОКВЭД</dt>
      <dd>{{ LEGAL_ENTITY.additionalOkved.join(', ') }}</dd>
      <dt>Система налогообложения</dt>
      <dd>{{ LEGAL_ENTITY.taxRegime }} — {{ LEGAL_ENTITY.vatNote }}</dd>
    </dl>

    <h2>Банковские реквизиты</h2>
    <dl>
      <dt>Банк</dt>
      <dd>{{ LEGAL_BANK.bankName }}</dd>
      <dt>Расчётный счёт</dt>
      <dd>{{ LEGAL_BANK.account }}</dd>
      <dt>Корреспондентский счёт</dt>
      <dd>{{ LEGAL_BANK.corrAccount }}</dd>
      <dt>БИК</dt>
      <dd>{{ LEGAL_BANK.bik }}</dd>
    </dl>
  </LegalPage>
</template>
