# Part of Odoo. See LICENSE file for full copyright and licensing details.


def get_api_key(provider_sudo):
    """Return the API key for N-Genius.

    Note: This method serves as a hook for modules that would extend N-Genius.

    :param recordset provider_sudo: The provider on which the key should be read, as a sudoed
                                    `payment.provider` record.
    :return: The API key
    :rtype: str
    """
    api_key = (provider_sudo.ngenius_api_key or '').strip()
    if api_key.lower().startswith('basic '):
        api_key = api_key[6:].strip()
    return api_key


def get_outlet_ref(provider_sudo):
    """Return the outlet reference for N-Genius.

    Note: This method serves as a hook for modules that would extend N-Genius.

    :param recordset provider_sudo: The provider on which the outlet ref should be read, as a sudoed
                                    `payment.provider` record.
    :return: The outlet reference
    :rtype: str
    """
    return provider_sudo.ngenius_outlet_ref


def format_billing_address(partner):
    """Format the billing address to comply with N-Genius API requirements.

    :param res.partner partner: The billing partner.
    :return: The formatted billing address.
    :rtype: dict
    """
    if not partner:
        return {}

    name_parts = (partner.name or '').split()
    if not name_parts:
        return {}

    billing_address = {
        'firstName': name_parts[0],
        'lastName': ' '.join(name_parts[1:]) if len(name_parts) > 1 else name_parts[0],
        'address1': (partner.street or '').strip(),
        'city': (partner.city or '').strip(),
        'countryCode': (partner.country_id.code or '').strip(),
    }

    if not all(billing_address[field] for field in ('address1', 'city', 'countryCode')):
        return {}

    return billing_address


def include_billing_address(tx_sudo):
    """Include the billing address of the partner to the N-Genius order payload.

    Note: `self.ensure_one()`

    :param payment.transaction tx_sudo: The sudoed transaction of the payment.
    :return: The formatted billing address for N-Genius API.
    :rtype: dict
    """
    tx_sudo.ensure_one()
    return format_billing_address(tx_sudo.partner_id)
